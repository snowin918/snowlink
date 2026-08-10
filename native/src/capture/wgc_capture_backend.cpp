#include "snowlink/capture/wgc_capture_backend.h"

#include <Windows.h>
#include <appmodel.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Metadata.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <winrt/Windows.Security.Authorization.AppCapabilityAccess.h>
#include <wrl.h>

#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>

namespace capture = winrt::Windows::Graphics::Capture;
namespace direct3d = winrt::Windows::Graphics::DirectX::Direct3D11;
namespace metadata = winrt::Windows::Foundation::Metadata;
using Microsoft::WRL::ComPtr;

namespace snowlink {
namespace {

constexpr int32_t kInvalidArgument = -1;
constexpr int32_t kNotRunning = -2;
constexpr int32_t kNoFrame = -3;
constexpr int32_t kNotSupported = -4;

HMONITOR monitor_by_index(int32_t wanted) noexcept {
    if (wanted < 0) return nullptr;
    struct Data { int32_t wanted; int32_t current; HMONITOR result; } data{wanted, 0, nullptr};
    EnumDisplayMonitors(nullptr, nullptr,
        [](HMONITOR monitor, HDC, RECT*, LPARAM value) -> BOOL {
            auto& data = *reinterpret_cast<Data*>(value);
            if (data.current++ == data.wanted) {
                data.result = monitor;
                return FALSE;
            }
            return TRUE;
        }, reinterpret_cast<LPARAM>(&data));
    return data.result;
}

HRESULT make_winrt_device(ID3D11Device* device, direct3d::IDirect3DDevice& result) noexcept {
    ComPtr<IDXGIDevice> dxgi;
    HRESULT hr = device->QueryInterface(IID_PPV_ARGS(&dxgi));
    if (FAILED(hr)) return hr;
    ComPtr<IInspectable> inspectable;
    hr = CreateDirect3D11DeviceFromDXGIDevice(dxgi.Get(), inspectable.GetAddressOf());
    if (SUCCEEDED(hr)) {
        result = direct3d::IDirect3DDevice{
            inspectable.Detach(), winrt::take_ownership_from_abi};
    }
    return hr;
}

HRESULT texture_from_surface(direct3d::IDirect3DSurface const& surface,
                             ID3D11Texture2D** result) noexcept {
    if (!result) return E_POINTER;
    *result = nullptr;
    auto access = surface.as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
    return access->GetInterface(IID_PPV_ARGS(result));
}

bool has_package_identity() noexcept {
    UINT32 length = 0;
    const LONG result = GetCurrentPackageFullName(&length, nullptr);
    return result != APPMODEL_ERROR_NO_PACKAGE;
}

} // namespace

struct WgcCaptureBackend::Impl : std::enable_shared_from_this<Impl> {
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    direct3d::IDirect3DDevice winrt_device{nullptr};
    capture::GraphicsCaptureItem item{nullptr};
    capture::Direct3D11CaptureFramePool pool{nullptr};
    capture::GraphicsCaptureSession session{nullptr};
    winrt::event_token frame_token{};
    winrt::event_token closed_token{};

    // Snowlink-owned DEFAULT-usage textures. CopyResource is a GPU operation;
    // these are never mapped and no staging texture exists.
    std::array<ComPtr<ID3D11Texture2D>, 2> slots;
    uint32_t published_slot = 0;
    uint64_t published_id = 0;
    mutable std::mutex mutex;
    std::condition_variable callbacks_done;
    std::atomic<uint32_t> callbacks{0};
    std::atomic<bool> stopping{false};
    std::atomic<bool> active{false};
    std::atomic<bool> access_lost{false};
    std::atomic<bool> device_lost{false};
    std::atomic<uint64_t> frames{0};
    std::atomic<uint64_t> replaced{0};
    std::atomic<uint64_t> last_acquired{0};
    std::atomic<uint64_t> recreates{0};
    std::atomic<int32_t> width{0};
    std::atomic<int32_t> height{0};
    bool cursor = false;
    bool borderless_available = false;
    bool borderless_granted = false;
    bool border_active = true;

    void callback_enter() noexcept { callbacks.fetch_add(1, std::memory_order_acq_rel); }
    void callback_leave() noexcept {
        if (callbacks.fetch_sub(1, std::memory_order_acq_rel) == 1) callbacks_done.notify_all();
    }

    HRESULT allocate_slots(D3D11_TEXTURE2D_DESC desc) noexcept {
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.CPUAccessFlags = 0;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
        desc.MiscFlags &= D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX;
        std::array<ComPtr<ID3D11Texture2D>, 2> fresh;
        for (auto& slot : fresh) {
            const HRESULT hr = device->CreateTexture2D(&desc, nullptr, &slot);
            if (FAILED(hr)) return hr;
        }
        std::scoped_lock lock(mutex);
        slots = std::move(fresh);
        published_id = 0;
        published_slot = 0;
        width.store(static_cast<int32_t>(desc.Width));
        height.store(static_cast<int32_t>(desc.Height));
        return S_OK;
    }

    void on_frame(capture::Direct3D11CaptureFramePool const& sender) noexcept {
        if (stopping.load()) return;
        callback_enter();
        struct Exit { Impl* self; ~Exit() { self->callback_leave(); } } exit{this};
        try {
            auto frame = sender.TryGetNextFrame();
            if (!frame) return;
            ComPtr<ID3D11Texture2D> source;
            winrt::check_hresult(texture_from_surface(frame.Surface(), &source));
            D3D11_TEXTURE2D_DESC desc{};
            source->GetDesc(&desc);

            const auto content = frame.ContentSize();
            const bool resized = content.Width > 0 && content.Height > 0 &&
                (content.Width != width.load() || content.Height != height.load());
            const bool recreate = resized || !slots[0];
            if (recreate) {
                desc.Width = static_cast<UINT>(content.Width);
                desc.Height = static_cast<UINT>(content.Height);
                winrt::check_hresult(allocate_slots(desc));
            }

            {
                std::scoped_lock lock(mutex);
                const uint32_t next = (published_slot + 1u) % 2u;
                context->CopyResource(slots[next].Get(), source.Get());
                if (published_id != 0 && last_acquired.load() < published_id) replaced.fetch_add(1);
                published_slot = next;
                ++published_id;
                frames.fetch_add(1);
            }

            if (recreate) {
                source.Reset();
                frame.Close(); // all frame-pool references must be released first
                pool.Recreate(winrt_device,
                    winrt::Windows::Graphics::DirectX::DirectXPixelFormat::B8G8R8A8UIntNormalized,
                    2, content);
                recreates.fetch_add(1);
            }

            const HRESULT removed = device->GetDeviceRemovedReason();
            if (FAILED(removed)) {
                device_lost.store(true);
                active.store(false);
            }
        } catch (...) {
            if (device && FAILED(device->GetDeviceRemovedReason())) device_lost.store(true);
        }
    }

    void close() noexcept {
        stopping.store(true);
        active.store(false);
        try { if (pool && frame_token.value) pool.FrameArrived(frame_token); } catch (...) {}
        try { if (item && closed_token.value) item.Closed(closed_token); } catch (...) {}
        try { if (session) session.Close(); } catch (...) {}
        try { if (pool) pool.Close(); } catch (...) {}
        std::unique_lock lock(mutex);
        callbacks_done.wait_for(lock, std::chrono::seconds(2), [this] { return callbacks.load() == 0; });
        slots = {};
        session = nullptr;
        pool = nullptr;
        item = nullptr;
        winrt_device = nullptr;
        context.Reset();
        device.Reset();
    }
};

WgcCaptureBackend::WgcCaptureBackend() = default;
WgcCaptureBackend::~WgcCaptureBackend() { stop(); }

int32_t WgcCaptureBackend::start(const CaptureConfig& config) {
    stop();
    try {
        const HRESULT apartment_hr = RoInitialize(RO_INIT_MULTITHREADED);
        if (FAILED(apartment_hr) && apartment_hr != RPC_E_CHANGED_MODE)
            return static_cast<int32_t>(apartment_hr);
        if (!capture::GraphicsCaptureSession::IsSupported()) return kNotSupported;
        auto impl = std::make_shared<Impl>();
        impl->cursor = capture_cursor_in_video_;

        UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
        D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
        D3D_FEATURE_LEVEL level{};
        HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags,
            levels, ARRAYSIZE(levels), D3D11_SDK_VERSION, &impl->device, &level, &impl->context);
        if (FAILED(hr)) return static_cast<int32_t>(hr);
        hr = make_winrt_device(impl->device.Get(), impl->winrt_device);
        if (FAILED(hr)) return static_cast<int32_t>(hr);

        HMONITOR monitor = config.display_id
            ? reinterpret_cast<HMONITOR>(static_cast<uintptr_t>(config.display_id))
            : monitor_by_index(config.monitor_index);
        if (!monitor) return kInvalidArgument;

        auto factory = winrt::get_activation_factory<capture::GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
        winrt::check_hresult(factory->CreateForMonitor(
            monitor, winrt::guid_of<capture::GraphicsCaptureItem>(), winrt::put_abi(impl->item)));
        auto size = impl->item.Size();
        if (size.Width <= 0 || size.Height <= 0) return kInvalidArgument;

        // Borderless access is a packaged-app feature. API presence is checked
        // before requesting; denial/missing identity is non-fatal and preserves
        // the standard yellow capture border.
        impl->borderless_available = has_package_identity() &&
            metadata::ApiInformation::IsTypePresent(
                L"Windows.Graphics.Capture.GraphicsCaptureAccess");
        if (impl->borderless_available) {
            try {
                const auto result = capture::GraphicsCaptureAccess::RequestAccessAsync(
                    capture::GraphicsCaptureAccessKind::Borderless).get();
                impl->borderless_granted = result == winrt::Windows::Security::Authorization::AppCapabilityAccess::AppCapabilityAccessStatus::Allowed;
            } catch (...) { impl->borderless_granted = false; }
        }

        impl->pool = capture::Direct3D11CaptureFramePool::CreateFreeThreaded(
            impl->winrt_device,
            winrt::Windows::Graphics::DirectX::DirectXPixelFormat::B8G8R8A8UIntNormalized,
            2, size);
        std::weak_ptr<Impl> weak = impl;
        impl->frame_token = impl->pool.FrameArrived([weak](auto const& sender, auto const&) {
            if (auto strong = weak.lock()) strong->on_frame(sender);
        });
        impl->closed_token = impl->item.Closed([weak](auto const&, auto const&) {
            if (auto strong = weak.lock()) {
                strong->access_lost.store(true);
                strong->active.store(false);
            }
        });
        impl->session = impl->pool.CreateCaptureSession(impl->item);
        try { impl->session.IsCursorCaptureEnabled(impl->cursor); } catch (...) {}
        if (impl->borderless_granted) {
            try { impl->session.IsBorderRequired(false); impl->border_active = false; }
            catch (...) { impl->border_active = true; }
        }
        impl->session.StartCapture();
        impl->width.store(size.Width);
        impl->height.store(size.Height);
        impl->active.store(true);
        impl_ = std::move(impl);
        return 0;
    } catch (winrt::hresult_error const& error) {
        stop();
        return static_cast<int32_t>(error.code().value);
    } catch (...) {
        stop();
        return E_FAIL;
    }
}

int32_t WgcCaptureBackend::stop() {
    auto impl = std::move(impl_);
    if (impl) impl->close();
    return 0;
}

int32_t WgcCaptureBackend::get_latest_frame(ID3D11Texture2D** texture, uint64_t* id) const {
    if (!texture || !id) return kInvalidArgument;
    *texture = nullptr;
    *id = 0;
    auto impl = impl_;
    if (!impl) return kNotRunning;
    std::scoped_lock lock(impl->mutex);
    if (!impl->published_id || !impl->slots[impl->published_slot]) return kNoFrame;
    impl->slots[impl->published_slot].CopyTo(texture);
    *id = impl->published_id;
    impl->last_acquired.store(*id);
    return 0;
}

int32_t WgcCaptureBackend::set_capture_cursor_in_video(bool enabled) {
    capture_cursor_in_video_ = enabled;
    auto impl = impl_;
    if (!impl) return 0;
    try { impl->session.IsCursorCaptureEnabled(enabled); impl->cursor = enabled; return 0; }
    catch (winrt::hresult_error const& error) { return static_cast<int32_t>(error.code().value); }
}

int32_t WgcCaptureBackend::get_capture_status(CaptureStatus& status) const {
    status = {};
    status.capture_border_active = true;
    status.capture_cursor_in_video = capture_cursor_in_video_;
    auto impl = impl_;
    if (!impl) return 0;
    status.borderless_capture_available = impl->borderless_available;
    status.borderless_capture_granted = impl->borderless_granted;
    status.capture_border_active = impl->border_active;
    status.capture_cursor_in_video = impl->cursor;
    status.capture_active = impl->active.load();
    status.access_lost = impl->access_lost.load();
    status.device_lost = impl->device_lost.load();
    status.width = impl->width.load();
    status.height = impl->height.load();
    return 0;
}

int32_t WgcCaptureBackend::get_stats(CaptureBackendStats& stats) const {
    stats = {};
    auto impl = impl_;
    if (!impl) return 0;
    stats.frames_captured = impl->frames.load();
    stats.frames_replaced = impl->replaced.load();
    stats.frame_pool_recreates = impl->recreates.load();
    return 0;
}

} // namespace snowlink
