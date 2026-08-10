#include "snowlink/renderer.h"

#include <dxgi1_2.h>
#include <wrl/client.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

using Microsoft::WRL::ComPtr;

namespace snowlink {

class Renderer::State {
public:
    HWND hwnd{};
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDXGISwapChain1> swap;
    ComPtr<ID3D11VideoDevice> video_device;
    ComPtr<ID3D11VideoContext> video_context;
    ComPtr<ID3D11VideoProcessorEnumerator> enumerator;
    ComPtr<ID3D11VideoProcessor> processor;
    ComPtr<ID3D11Texture2D> latest;
    std::uint32_t latest_subresource = 0;
    std::uint64_t latest_id = 0;
    std::uint64_t shown_id = 0;
    UINT processor_input_width = 0;
    UINT processor_input_height = 0;
    UINT processor_output_width = 0;
    UINT processor_output_height = 0;
    mutable std::mutex mutex;
    std::condition_variable wake;
    std::thread worker;
    bool stopping = false;
    bool visible = true;
    std::atomic<bool> resize_pending{true};
    RendererStats stats;
    std::chrono::steady_clock::time_point rate_mark{};
    std::uint64_t rate_frames = 0;

    HRESULT make_swap() {
        ComPtr<IDXGIDevice> dxgi_device;
        ComPtr<IDXGIAdapter> adapter;
        ComPtr<IDXGIFactory2> factory;
        HRESULT hr = device.As(&dxgi_device);
        if (FAILED(hr)) return hr;
        if (FAILED(hr = dxgi_device->GetAdapter(&adapter)) ||
            FAILED(hr = adapter->GetParent(IID_PPV_ARGS(&factory)))) {
            return hr;
        }
        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = 2;
        desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
        desc.Scaling = DXGI_SCALING_STRETCH;
        desc.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
        return factory->CreateSwapChainForHwnd(
            device.Get(), hwnd, &desc, nullptr, nullptr, &swap);
    }

    HRESULT ensure_processor(const D3D11_TEXTURE2D_DESC& input, UINT output_width,
                             UINT output_height) {
        if (enumerator && processor && processor_input_width == input.Width &&
            processor_input_height == input.Height &&
            processor_output_width == output_width &&
            processor_output_height == output_height) {
            return S_OK;
        }
        enumerator.Reset();
        processor.Reset();
        D3D11_VIDEO_PROCESSOR_CONTENT_DESC content{};
        content.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
        // These are passthrough timing hints, but a valid rational is required
        // by video-processor drivers on all supported adapters.
        content.InputFrameRate = {60, 1};
        content.InputWidth = input.Width;
        content.InputHeight = input.Height;
        content.OutputFrameRate = {60, 1};
        content.OutputWidth = output_width;
        content.OutputHeight = output_height;
        content.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;
        HRESULT hr = video_device->CreateVideoProcessorEnumerator(&content, &enumerator);
        if (FAILED(hr)) return hr;
        hr = video_device->CreateVideoProcessor(enumerator.Get(), 0, &processor);
        if (FAILED(hr)) {
            enumerator.Reset();
            return hr;
        }
        processor_input_width = input.Width;
        processor_input_height = input.Height;
        processor_output_width = output_width;
        processor_output_height = output_height;
        return S_OK;
    }

    HRESULT render(ID3D11Texture2D* input, std::uint32_t subresource) {
        if (!IsWindow(hwnd)) return E_HANDLE;
        RECT client{};
        if (!GetClientRect(hwnd, &client)) return HRESULT_FROM_WIN32(GetLastError());
        const UINT output_width = static_cast<UINT>(client.right - client.left);
        const UINT output_height = static_cast<UINT>(client.bottom - client.top);
        if (!output_width || !output_height || IsIconic(hwnd) || !IsWindowVisible(hwnd)) {
            return S_FALSE;
        }
        if (!swap) {
            const HRESULT hr = make_swap();
            if (FAILED(hr)) return hr;
        }

        DXGI_SWAP_CHAIN_DESC1 current{};
        HRESULT hr = swap->GetDesc1(&current);
        if (FAILED(hr)) return hr;
        if (resize_pending.exchange(false) || current.Width != output_width ||
            current.Height != output_height) {
            context->ClearState();
            hr = swap->ResizeBuffers(
                0, output_width, output_height, DXGI_FORMAT_UNKNOWN, 0);
            if (FAILED(hr)) {
                resize_pending.store(true);
                swap.Reset();
                return hr;
            }
            enumerator.Reset();
            processor.Reset();
        }

        D3D11_TEXTURE2D_DESC input_desc{};
        input->GetDesc(&input_desc);
        const UINT mip_levels = input_desc.MipLevels ? input_desc.MipLevels : 1;
        if (subresource >= mip_levels * input_desc.ArraySize) return E_INVALIDARG;
        if (FAILED(hr = ensure_processor(input_desc, output_width, output_height))) return hr;

        ComPtr<ID3D11Texture2D> back;
        if (FAILED(hr = swap->GetBuffer(0, IID_PPV_ARGS(&back)))) return hr;
        ComPtr<ID3D11RenderTargetView> render_target;
        if (FAILED(hr = device->CreateRenderTargetView(
                       back.Get(), nullptr, &render_target))) {
            return hr;
        }
        constexpr float black[4] = {0.0f, 0.0f, 0.0f, 1.0f};
        context->ClearRenderTargetView(render_target.Get(), black);

        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC input_view_desc{};
        input_view_desc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        input_view_desc.Texture2D.MipSlice = subresource % mip_levels;
        input_view_desc.Texture2D.ArraySlice = subresource / mip_levels;
        D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC output_view_desc{};
        output_view_desc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
        output_view_desc.Texture2D.MipSlice = 0;
        ComPtr<ID3D11VideoProcessorInputView> input_view;
        ComPtr<ID3D11VideoProcessorOutputView> output_view;
        if (FAILED(hr = video_device->CreateVideoProcessorInputView(
                       input, enumerator.Get(), &input_view_desc, &input_view)) ||
            FAILED(hr = video_device->CreateVideoProcessorOutputView(
                       back.Get(), enumerator.Get(), &output_view_desc, &output_view))) {
            return hr;
        }

        const RECT source{
            0, 0, static_cast<LONG>(input_desc.Width),
            static_cast<LONG>(input_desc.Height)};
        RECT destination{};
        const double source_aspect =
            static_cast<double>(input_desc.Width) / input_desc.Height;
        const double output_aspect =
            static_cast<double>(output_width) / output_height;
        if (output_aspect > source_aspect) {
            const LONG width = static_cast<LONG>(output_height * source_aspect);
            destination = {
                (static_cast<LONG>(output_width) - width) / 2, 0,
                (static_cast<LONG>(output_width) + width) / 2,
                static_cast<LONG>(output_height)};
        } else {
            const LONG height = static_cast<LONG>(output_width / source_aspect);
            destination = {
                0, (static_cast<LONG>(output_height) - height) / 2,
                static_cast<LONG>(output_width),
                (static_cast<LONG>(output_height) + height) / 2};
        }
        video_context->VideoProcessorSetStreamSourceRect(
            processor.Get(), 0, TRUE, &source);
        video_context->VideoProcessorSetStreamDestRect(
            processor.Get(), 0, TRUE, &destination);
        D3D11_VIDEO_PROCESSOR_STREAM stream{};
        stream.Enable = TRUE;
        stream.pInputSurface = input_view.Get();
        hr = video_context->VideoProcessorBlt(
            processor.Get(), output_view.Get(), 0, 1, &stream);
        if (FAILED(hr)) return hr;
        return swap->Present(0, 0);
    }

    void run() {
        for (;;) {
            ComPtr<ID3D11Texture2D> frame;
            std::uint32_t subresource = 0;
            std::uint64_t id = 0;
            {
                std::unique_lock lock(mutex);
                wake.wait(lock, [&] {
                    return stopping ||
                        (visible && latest &&
                         (latest_id != shown_id || resize_pending.load()));
                });
                if (stopping) return;
                frame = latest;
                subresource = latest_subresource;
                id = latest_id;
            }
            if (frame && render(frame.Get(), subresource) == S_OK) {
                std::lock_guard lock(mutex);
                shown_id = id;
                ++stats.frames_presented;
                ++rate_frames;
                const auto now = std::chrono::steady_clock::now();
                if (rate_mark.time_since_epoch().count() == 0) rate_mark = now;
                const double seconds =
                    std::chrono::duration<double>(now - rate_mark).count();
                if (seconds >= 0.5) {
                    stats.render_fps = rate_frames / seconds;
                    rate_frames = 0;
                    rate_mark = now;
                }
            } else {
                std::this_thread::sleep_for(std::chrono::milliseconds(16));
            }
        }
    }
};

Renderer::Renderer() : state_(std::make_unique<State>()) {}
Renderer::~Renderer() { shutdown(); }

int32_t Renderer::initialize(HWND hwnd, ID3D11Device* device) {
    shutdown();
    if (!hwnd || !device) return E_INVALIDARG;
    state_->hwnd = hwnd;
    state_->device = device;
    device->GetImmediateContext(&state_->context);
    HRESULT hr = device->QueryInterface(IID_PPV_ARGS(&state_->video_device));
    if (FAILED(hr)) return hr;
    if (FAILED(hr = state_->context.As(&state_->video_context))) return hr;
    state_->stopping = false;
    state_->visible = true;
    state_->resize_pending.store(true);
    state_->worker = std::thread([this] { state_->run(); });
    return S_OK;
}

int32_t Renderer::submit(ID3D11Texture2D* texture, std::uint32_t subresource_index,
                         std::uint64_t id) {
    if (!texture) return E_INVALIDARG;
    D3D11_TEXTURE2D_DESC desc{};
    texture->GetDesc(&desc);
    const UINT mip_levels = desc.MipLevels ? desc.MipLevels : 1;
    if (subresource_index >= mip_levels * desc.ArraySize) return E_INVALIDARG;
    std::lock_guard lock(state_->mutex);
    if (state_->latest_id != state_->shown_id) ++state_->stats.frames_replaced;
    state_->latest = texture;
    state_->latest_subresource = subresource_index;
    state_->latest_id = id;
    state_->wake.notify_one();
    return S_OK;
}

int32_t Renderer::resize() {
    state_->resize_pending.store(true);
    state_->wake.notify_one();
    return S_OK;
}

int32_t Renderer::set_visible(bool visible) {
    std::lock_guard lock(state_->mutex);
    state_->visible = visible;
    if (visible) state_->wake.notify_one();
    return S_OK;
}

int32_t Renderer::get_stats(RendererStats& stats) const {
    std::lock_guard lock(state_->mutex);
    stats = state_->stats;
    return S_OK;
}

int32_t Renderer::shutdown() {
    {
        std::lock_guard lock(state_->mutex);
        state_->stopping = true;
    }
    state_->wake.notify_all();
    if (state_->worker.joinable()) state_->worker.join();
    state_->latest.Reset();
    state_->swap.Reset();
    state_->processor.Reset();
    state_->enumerator.Reset();
    state_->video_context.Reset();
    state_->video_device.Reset();
    state_->context.Reset();
    state_->device.Reset();
    state_->hwnd = nullptr;
    state_->latest_subresource = 0;
    state_->latest_id = 0;
    state_->shown_id = 0;
    state_->processor_input_width = 0;
    state_->processor_input_height = 0;
    state_->processor_output_width = 0;
    state_->processor_output_height = 0;
    return S_OK;
}

} // namespace snowlink
