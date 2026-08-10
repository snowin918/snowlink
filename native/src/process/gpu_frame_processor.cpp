#include "snowlink/gpu_frame_processor.h"

#include <Windows.h>
#include <d3d11_1.h>
#include <d3d10.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <mutex>

using Microsoft::WRL::ComPtr;

namespace snowlink {
namespace {

DXGI_FORMAT to_dxgi(GpuPixelFormat format) noexcept {
    switch (format) {
    case GpuPixelFormat::Nv12: return DXGI_FORMAT_NV12;
    case GpuPixelFormat::P010: return DXGI_FORMAT_P010;
    case GpuPixelFormat::Bgra8: return DXGI_FORMAT_B8G8R8A8_UNORM;
    }
    return DXGI_FORMAT_UNKNOWN;
}

D3D11_VIDEO_PROCESSOR_ROTATION to_video_rotation(DXGI_MODE_ROTATION rotation) noexcept {
    switch (rotation) {
    case DXGI_MODE_ROTATION_ROTATE90: return D3D11_VIDEO_PROCESSOR_ROTATION_90;
    case DXGI_MODE_ROTATION_ROTATE180: return D3D11_VIDEO_PROCESSOR_ROTATION_180;
    case DXGI_MODE_ROTATION_ROTATE270: return D3D11_VIDEO_PROCESSOR_ROTATION_270;
    default: return D3D11_VIDEO_PROCESSOR_ROTATION_IDENTITY;
    }
}

bool swaps_axes(DXGI_MODE_ROTATION rotation) noexcept {
    return rotation == DXGI_MODE_ROTATION_ROTATE90 || rotation == DXGI_MODE_ROTATION_ROTATE270;
}

} // namespace

class GpuFrameProcessor::State {
public:
    mutable std::mutex mutex;
    GpuFrameProcessorConfig config{};
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<ID3D11VideoDevice> video_device;
    ComPtr<ID3D11VideoContext> video_context;
    ComPtr<ID3D11VideoContext1> video_context1;
    ComPtr<ID3D11VideoProcessorEnumerator> enumerator;
    ComPtr<ID3D11VideoProcessor> processor;
    std::array<ComPtr<ID3D11Texture2D>, 2> outputs;
    std::array<ComPtr<ID3D11VideoProcessorOutputView>, 2> output_views;
    std::array<ComPtr<ID3D11Texture2D>, 2> input_textures;
    std::array<ComPtr<ID3D11VideoProcessorInputView>, 2> input_views;
    D3D11_TEXTURE2D_DESC source_desc{};
    std::uint32_t output_width = 0;
    std::uint32_t output_height = 0;
    DXGI_FORMAT output_format = DXGI_FORMAT_UNKNOWN;
    std::uint32_t content_width = 0;
    std::uint32_t content_height = 0;
    std::size_t next_input_slot = 0;
    std::size_t next_slot = 0;
    std::size_t published_slot = 0;
    std::uint64_t published_id = 0;
    bool has_published = false;
    bool latest_observed = true;
    GpuFrameProcessorStats stats{};

    void clear_resources() {
        output_views = {};
        outputs = {};
        input_views = {};
        input_textures = {};
        processor.Reset();
        enumerator.Reset();
        video_context1.Reset();
        video_context.Reset();
        video_device.Reset();
        context.Reset();
        device.Reset();
        source_desc = {};
        output_width = output_height = 0;
        content_width = content_height = 0;
        output_format = DXGI_FORMAT_UNKNOWN;
        has_published = false;
        latest_observed = true;
        next_slot = 0;
        next_input_slot = 0;
    }

    HRESULT create_resources(ID3D11Texture2D* source, const D3D11_TEXTURE2D_DESC& desc,
                             const RECT& source_rect, std::uint32_t width, std::uint32_t height,
                             DXGI_FORMAT format) {
        ComPtr<ID3D11Device> new_device;
        source->GetDevice(&new_device);
        if (!new_device) return E_INVALIDARG;

        ComPtr<ID3D11DeviceContext> new_context;
        new_device->GetImmediateContext(&new_context);
        ComPtr<ID3D10Multithread> multithread;
        if (SUCCEEDED(new_context.As(&multithread))) multithread->SetMultithreadProtected(TRUE);
        ComPtr<ID3D11VideoDevice> new_video_device;
        ComPtr<ID3D11VideoContext> new_video_context;
        HRESULT hr = new_device.As(&new_video_device);
        if (FAILED(hr)) return hr;
        hr = new_context.As(&new_video_context);
        if (FAILED(hr)) return hr;

        D3D11_VIDEO_PROCESSOR_CONTENT_DESC content{};
        content.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
        content.InputFrameRate = {60, 1};
        content.InputWidth = static_cast<UINT>(source_rect.right - source_rect.left);
        content.InputHeight = static_cast<UINT>(source_rect.bottom - source_rect.top);
        content.OutputFrameRate = {60, 1};
        content.OutputWidth = width;
        content.OutputHeight = height;
        content.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

        ComPtr<ID3D11VideoProcessorEnumerator> new_enumerator;
        hr = new_video_device->CreateVideoProcessorEnumerator(&content, &new_enumerator);
        if (FAILED(hr)) return hr;
        UINT flags = 0;
        hr = new_enumerator->CheckVideoProcessorFormat(desc.Format, &flags);
        if (FAILED(hr) || !(flags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT))
            return FAILED(hr) ? hr : DXGI_ERROR_UNSUPPORTED;
        hr = new_enumerator->CheckVideoProcessorFormat(format, &flags);
        if (FAILED(hr) || !(flags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT))
            return FAILED(hr) ? hr : DXGI_ERROR_UNSUPPORTED;

        ComPtr<ID3D11VideoProcessor> new_processor;
        hr = new_video_device->CreateVideoProcessor(new_enumerator.Get(), 0, &new_processor);
        if (FAILED(hr)) return hr;

        std::array<ComPtr<ID3D11Texture2D>, 2> new_outputs;
        std::array<ComPtr<ID3D11VideoProcessorOutputView>, 2> new_views;
        D3D11_TEXTURE2D_DESC out{};
        out.Width = width; out.Height = height; out.MipLevels = 1; out.ArraySize = 1;
        out.Format = format; out.SampleDesc.Count = 1; out.Usage = D3D11_USAGE_DEFAULT;
        out.BindFlags = D3D11_BIND_RENDER_TARGET;
        D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC view{};
        view.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
        for (std::size_t i = 0; i < new_outputs.size(); ++i) {
            hr = new_device->CreateTexture2D(&out, nullptr, &new_outputs[i]);
            if (FAILED(hr)) return hr;
            hr = new_video_device->CreateVideoProcessorOutputView(
                new_outputs[i].Get(), new_enumerator.Get(), &view, &new_views[i]);
            if (FAILED(hr)) return hr;
        }

        clear_resources();
        device = std::move(new_device); context = std::move(new_context);
        video_device = std::move(new_video_device); video_context = std::move(new_video_context);
        video_context.As(&video_context1); // Rotation will report unsupported below if absent.
        enumerator = std::move(new_enumerator); processor = std::move(new_processor);
        outputs = std::move(new_outputs); output_views = std::move(new_views);
        source_desc = desc; output_width = width; output_height = height; output_format = format;
        content_width = static_cast<std::uint32_t>(source_rect.right - source_rect.left);
        content_height = static_cast<std::uint32_t>(source_rect.bottom - source_rect.top);
        ++stats.resolution_changes;
        return S_OK;
    }
};

GpuFrameProcessor::GpuFrameProcessor() : state_(std::make_unique<State>()) {}
GpuFrameProcessor::~GpuFrameProcessor() = default;

int32_t GpuFrameProcessor::configure(const GpuFrameProcessorConfig& config) {
    std::scoped_lock lock(state_->mutex);
    if (to_dxgi(config.output_format) == DXGI_FORMAT_UNKNOWN) return E_INVALIDARG;
    state_->config = config;
    return 0;
}

int32_t GpuFrameProcessor::process_frame(ID3D11Texture2D* source, std::uint64_t frame_id) {
    if (!source) return E_POINTER;
    const auto begun = std::chrono::steady_clock::now();
    std::scoped_lock lock(state_->mutex);
    D3D11_TEXTURE2D_DESC desc{};
    source->GetDesc(&desc);
    RECT crop = state_->config.crop;
    if (crop.right <= crop.left || crop.bottom <= crop.top)
        crop = {0, 0, static_cast<LONG>(desc.Width), static_cast<LONG>(desc.Height)};
    if (crop.left < 0 || crop.top < 0 || crop.right > static_cast<LONG>(desc.Width) ||
        crop.bottom > static_cast<LONG>(desc.Height)) return E_INVALIDARG;
    const auto crop_width = static_cast<std::uint32_t>(crop.right - crop.left);
    const auto crop_height = static_cast<std::uint32_t>(crop.bottom - crop.top);
    const std::uint32_t natural_width = swaps_axes(state_->config.rotation) ? crop_height : crop_width;
    const std::uint32_t natural_height = swaps_axes(state_->config.rotation) ? crop_width : crop_height;
    std::uint32_t width = state_->config.target_width ? state_->config.target_width : natural_width;
    std::uint32_t height = state_->config.target_height ? state_->config.target_height : natural_height;
    const DXGI_FORMAT format = to_dxgi(state_->config.output_format);
    if ((format == DXGI_FORMAT_NV12 || format == DXGI_FORMAT_P010) && ((width | height) & 1u))
        return E_INVALIDARG;

    ComPtr<ID3D11Device> incoming_device;
    source->GetDevice(&incoming_device);
    const bool recreate = incoming_device.Get() != state_->device.Get() ||
        desc.Width != state_->source_desc.Width || desc.Height != state_->source_desc.Height ||
        desc.Format != state_->source_desc.Format || width != state_->output_width ||
        height != state_->output_height || format != state_->output_format ||
        crop_width != state_->content_width || crop_height != state_->content_height;
    if (recreate) {
        const HRESULT hr = state_->create_resources(source, desc, crop, width, height, format);
        if (FAILED(hr)) return hr;
    }

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC input_desc{};
    input_desc.FourCC = 0;
    input_desc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    input_desc.Texture2D.MipSlice = 0;
    input_desc.Texture2D.ArraySlice = 0;
    ID3D11VideoProcessorInputView* input_view = nullptr;
    for (std::size_t i = 0; i < state_->input_textures.size(); ++i) {
        if (state_->input_textures[i].Get() == source) input_view = state_->input_views[i].Get();
    }
    HRESULT hr = S_OK;
    if (!input_view) {
        const std::size_t input_slot = state_->next_input_slot;
        ComPtr<ID3D11VideoProcessorInputView> new_view;
        hr = state_->video_device->CreateVideoProcessorInputView(
            source, state_->enumerator.Get(), &input_desc, &new_view);
        if (FAILED(hr)) return hr;
        state_->input_textures[input_slot] = source;
        state_->input_views[input_slot] = std::move(new_view);
        input_view = state_->input_views[input_slot].Get();
        state_->next_input_slot = (input_slot + 1) % state_->input_textures.size();
    }

    RECT destination{0, 0, static_cast<LONG>(width), static_cast<LONG>(height)};
    state_->video_context->VideoProcessorSetStreamSourceRect(state_->processor.Get(), 0, TRUE, &crop);
    state_->video_context->VideoProcessorSetStreamDestRect(state_->processor.Get(), 0, TRUE, &destination);
    state_->video_context->VideoProcessorSetOutputTargetRect(state_->processor.Get(), TRUE, &destination);
    if (state_->config.rotation != DXGI_MODE_ROTATION_IDENTITY &&
        state_->config.rotation != DXGI_MODE_ROTATION_UNSPECIFIED) {
        if (!state_->video_context1) return DXGI_ERROR_UNSUPPORTED;
        state_->video_context1->VideoProcessorSetStreamRotation(
            state_->processor.Get(), 0, TRUE, to_video_rotation(state_->config.rotation));
    } else if (state_->video_context1) {
        state_->video_context1->VideoProcessorSetStreamRotation(
            state_->processor.Get(), 0, FALSE, D3D11_VIDEO_PROCESSOR_ROTATION_IDENTITY);
    }

    const std::size_t slot = state_->next_slot;
    D3D11_VIDEO_PROCESSOR_STREAM stream{};
    stream.Enable = TRUE; stream.pInputSurface = input_view;
    hr = state_->video_context->VideoProcessorBlt(
        state_->processor.Get(), state_->output_views[slot].Get(), 0, 1, &stream);
    if (FAILED(hr)) return hr;
    if (state_->has_published && !state_->latest_observed) ++state_->stats.frames_replaced;
    state_->published_slot = slot; state_->published_id = frame_id;
    state_->has_published = true; state_->latest_observed = false;
    state_->next_slot = (slot + 1) % state_->outputs.size();
    ++state_->stats.gpu_preprocess_frames;
    const double milliseconds = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - begun).count();
    const double count = static_cast<double>(state_->stats.gpu_preprocess_frames);
    state_->stats.preprocess_latency_ms += (milliseconds - state_->stats.preprocess_latency_ms) / count;
    return 0;
}

int32_t GpuFrameProcessor::get_latest_frame(ID3D11Texture2D** texture, std::uint64_t* frame_id) {
    if (!texture || !frame_id) return E_POINTER;
    *texture = nullptr; *frame_id = 0;
    std::scoped_lock lock(state_->mutex);
    if (!state_->has_published) return DXGI_ERROR_NOT_FOUND;
    *texture = state_->outputs[state_->published_slot].Get();
    (*texture)->AddRef();
    *frame_id = state_->published_id;
    state_->latest_observed = true;
    return 0;
}

int32_t GpuFrameProcessor::get_stats(GpuFrameProcessorStats& stats) const {
    std::scoped_lock lock(state_->mutex); stats = state_->stats; return 0;
}

void GpuFrameProcessor::reset() {
    std::scoped_lock lock(state_->mutex); state_->clear_resources();
}

} // namespace snowlink
