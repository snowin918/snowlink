#include "snowlink/capture/dxgi_capture_backend.h"

#include <Windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi1_2.h>
#include <wrl.h>

#include <array>
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>

using Microsoft::WRL::ComPtr;

namespace snowlink {
namespace {
constexpr int32_t kInvalidArgument = -1;
constexpr int32_t kNotRunning = -2;
constexpr int32_t kNoFrame = -3;

HMONITOR monitor_by_index(int32_t wanted) noexcept {
    if (wanted < 0) return nullptr;
    struct Data { int32_t wanted; int32_t current; HMONITOR result; } data{wanted, 0, nullptr};
    EnumDisplayMonitors(nullptr, nullptr, [](HMONITOR monitor, HDC, RECT*, LPARAM value) -> BOOL {
        auto& data = *reinterpret_cast<Data*>(value);
        if (data.current++ == data.wanted) { data.result = monitor; return FALSE; }
        return TRUE;
    }, reinterpret_cast<LPARAM>(&data));
    return data.result;
}

HRESULT find_output(HMONITOR monitor, ComPtr<IDXGIAdapter1>& adapter,
                    ComPtr<IDXGIOutput1>& output) noexcept {
    ComPtr<IDXGIFactory1> factory;
    HRESULT hr = CreateDXGIFactory1(IID_PPV_ARGS(&factory));
    if (FAILED(hr)) return hr;
    for (UINT ai = 0;; ++ai) {
        ComPtr<IDXGIAdapter1> candidate;
        hr = factory->EnumAdapters1(ai, &candidate);
        if (hr == DXGI_ERROR_NOT_FOUND) break;
        if (FAILED(hr)) return hr;
        for (UINT oi = 0;; ++oi) {
            ComPtr<IDXGIOutput> base;
            hr = candidate->EnumOutputs(oi, &base);
            if (hr == DXGI_ERROR_NOT_FOUND) break;
            if (FAILED(hr)) return hr;
            DXGI_OUTPUT_DESC desc{};
            if (SUCCEEDED(base->GetDesc(&desc)) && desc.Monitor == monitor && desc.AttachedToDesktop) {
                hr = base.As(&output);
                if (SUCCEEDED(hr)) adapter = candidate;
                return hr;
            }
        }
    }
    return DXGI_ERROR_NOT_FOUND;
}

class FrameLease {
public:
    explicit FrameLease(IDXGIOutputDuplication* duplication) : duplication_(duplication) {}
    void acquired() noexcept { acquired_ = true; }
    ~FrameLease() { if (acquired_) duplication_->ReleaseFrame(); }
private:
    IDXGIOutputDuplication* duplication_;
    bool acquired_ = false;
};
} // namespace

struct DxgiCaptureBackend::Impl {
    CaptureConfig config{};
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<ID3D11Device> consumer_device;
    ComPtr<ID3D11DeviceContext> consumer_context;
    ComPtr<IDXGIOutputDuplication> duplication;
    std::array<ComPtr<ID3D11Texture2D>, 2> slots;
    std::array<ComPtr<IDXGIKeyedMutex>, 2> producer_mutexes;
    std::array<ComPtr<ID3D11Texture2D>, 2> consumer_shared_slots;
    std::array<ComPtr<IDXGIKeyedMutex>, 2> consumer_mutexes;
    std::array<ComPtr<ID3D11Texture2D>, 2> consumer_slots;
    uint32_t published_slot = 0;
    uint32_t consumer_slot = 0;
    uint64_t published_id = 0;
    uint64_t materialized_id = 0;
    FrameMetadata metadata;
    PointerState pointer;
    mutable std::mutex mutex;
    std::thread worker;
    std::atomic<bool> stopping{false}, active{false}, access_lost{false}, device_lost{false};
    std::atomic<int32_t> width{0}, height{0};
    std::atomic<int32_t> rotation{DXGI_MODE_ROTATION_UNSPECIFIED};
    std::atomic<uint64_t> frames{0}, replaced{0}, last_acquired{0}, recreates{0};
    std::atomic<uint64_t> timeouts{0}, recoveries{0}, dirty_count{0}, move_count{0}, pointer_count{0};

    HRESULT create_duplication() noexcept {
        duplication.Reset(); context.Reset(); device.Reset();
        consumer_context.Reset(); consumer_device.Reset();
        { std::scoped_lock lock(mutex); slots = {}; producer_mutexes = {};
          consumer_shared_slots = {}; consumer_mutexes = {}; consumer_slots = {};
          published_id = materialized_id = 0; }
        const HMONITOR monitor = config.display_id
            ? reinterpret_cast<HMONITOR>(static_cast<uintptr_t>(config.display_id))
            : monitor_by_index(config.monitor_index);
        if (!monitor) return E_INVALIDARG;
        ComPtr<IDXGIAdapter1> adapter;
        ComPtr<IDXGIOutput1> output;
        HRESULT hr = find_output(monitor, adapter, output);
        if (FAILED(hr)) return hr;
        UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT | D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
        D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
        D3D_FEATURE_LEVEL level{};
        hr = D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, flags,
            levels, ARRAYSIZE(levels), D3D11_SDK_VERSION, &device, &level, &context);
        if (FAILED(hr)) return hr;
        hr = D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, flags,
            levels, ARRAYSIZE(levels), D3D11_SDK_VERSION,
            &consumer_device, &level, &consumer_context);
        if (FAILED(hr)) return hr;
        hr = output->DuplicateOutput(device.Get(), &duplication);
        if (FAILED(hr)) return hr;
        DXGI_OUTDUPL_DESC desc{};
        duplication->GetDesc(&desc);
        width.store(static_cast<int32_t>(desc.ModeDesc.Width));
        height.store(static_cast<int32_t>(desc.ModeDesc.Height));
        rotation.store(static_cast<int32_t>(desc.Rotation));
        access_lost.store(false);
        active.store(true);
        return S_OK;
    }

    HRESULT ensure_slots(const D3D11_TEXTURE2D_DESC& source_desc) noexcept {
        std::scoped_lock lock(mutex);
        if (slots[0]) {
            D3D11_TEXTURE2D_DESC current{}; slots[0]->GetDesc(&current);
            if (current.Width == source_desc.Width && current.Height == source_desc.Height &&
                current.Format == source_desc.Format) return S_OK;
        }
        D3D11_TEXTURE2D_DESC desc = source_desc;
        desc.Usage = D3D11_USAGE_DEFAULT; desc.CPUAccessFlags = 0;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
        desc.MiscFlags = D3D11_RESOURCE_MISC_SHARED_NTHANDLE |
            D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX;
        std::array<ComPtr<ID3D11Texture2D>, 2> fresh;
        std::array<ComPtr<IDXGIKeyedMutex>, 2> fresh_producer_mutexes;
        std::array<ComPtr<ID3D11Texture2D>, 2> fresh_consumer_shared;
        std::array<ComPtr<IDXGIKeyedMutex>, 2> fresh_consumer_mutexes;
        std::array<ComPtr<ID3D11Texture2D>, 2> fresh_consumer_slots;
        ComPtr<ID3D11Device1> consumer_device1;
        HRESULT hr = consumer_device.As(&consumer_device1);
        if (FAILED(hr)) return hr;
        for (std::size_t i = 0; i < fresh.size(); ++i) {
            hr = device->CreateTexture2D(&desc, nullptr, &fresh[i]);
            if (FAILED(hr)) return hr;
            if (FAILED(hr = fresh[i].As(&fresh_producer_mutexes[i]))) return hr;
            ComPtr<IDXGIResource1> resource;
            if (FAILED(hr = fresh[i].As(&resource))) return hr;
            HANDLE shared = nullptr;
            hr = resource->CreateSharedHandle(nullptr, DXGI_SHARED_RESOURCE_READ |
                DXGI_SHARED_RESOURCE_WRITE, nullptr, &shared);
            if (FAILED(hr)) return hr;
            hr = consumer_device1->OpenSharedResource1(
                shared, IID_PPV_ARGS(&fresh_consumer_shared[i]));
            CloseHandle(shared);
            if (FAILED(hr) || FAILED(hr = fresh_consumer_shared[i].As(&fresh_consumer_mutexes[i])))
                return FAILED(hr) ? hr : E_NOINTERFACE;
            D3D11_TEXTURE2D_DESC local = desc; local.MiscFlags = 0;
            if (FAILED(hr = consumer_device->CreateTexture2D(
                    &local, nullptr, &fresh_consumer_slots[i]))) return hr;
        }
        slots = std::move(fresh); producer_mutexes = std::move(fresh_producer_mutexes);
        consumer_shared_slots = std::move(fresh_consumer_shared);
        consumer_mutexes = std::move(fresh_consumer_mutexes);
        consumer_slots = std::move(fresh_consumer_slots);
        published_id = materialized_id = 0; published_slot = consumer_slot = 0;
        width.store(static_cast<int32_t>(desc.Width)); height.store(static_cast<int32_t>(desc.Height));
        return S_OK;
    }

    void collect_metadata(const DXGI_OUTDUPL_FRAME_INFO& info, uint32_t w, uint32_t h) {
        std::scoped_lock lock(mutex);
        LARGE_INTEGER qpc{}; QueryPerformanceCounter(&qpc);
        metadata.timestamp_qpc = static_cast<uint64_t>(qpc.QuadPart);
        metadata.width = w; metadata.height = h;
        metadata.desktop_updated = info.AccumulatedFrames != 0;
        metadata.pointer_updated = info.LastMouseUpdateTime.QuadPart != 0;

        UINT required = 0;
        duplication->GetFrameMoveRects(0, nullptr, &required);
        if (required) {
            metadata.move_rects.resize(required / sizeof(DXGI_OUTDUPL_MOVE_RECT));
            if (SUCCEEDED(duplication->GetFrameMoveRects(required,
                    metadata.move_rects.data(), &required)))
                metadata.move_rects.resize(required / sizeof(DXGI_OUTDUPL_MOVE_RECT));
            else metadata.move_rects.clear();
        } else metadata.move_rects.clear();
        required = 0;
        duplication->GetFrameDirtyRects(0, nullptr, &required);
        if (required) {
            metadata.dirty_rects.resize(required / sizeof(RECT));
            if (SUCCEEDED(duplication->GetFrameDirtyRects(required,
                    metadata.dirty_rects.data(), &required)))
                metadata.dirty_rects.resize(required / sizeof(RECT));
            else metadata.dirty_rects.clear();
        } else metadata.dirty_rects.clear();

        if (metadata.pointer_updated) {
            pointer.position = info.PointerPosition.Position;
            pointer.visible = info.PointerPosition.Visible != FALSE;
            ++pointer_count;
        }
        pointer.shape_changed = info.PointerShapeBufferSize != 0;
        if (info.PointerShapeBufferSize) {
            pointer.shape.resize(info.PointerShapeBufferSize);
            UINT used = 0;
            if (SUCCEEDED(duplication->GetFramePointerShape(
                    static_cast<UINT>(pointer.shape.size()), pointer.shape.data(),
                    &used, &pointer.shape_info))) {
                pointer.shape.resize(used);
                pointer.hotspot = pointer.shape_info.HotSpot;
            }
        }
        dirty_count.fetch_add(metadata.dirty_rects.size());
        move_count.fetch_add(metadata.move_rects.size());
    }

    void run() noexcept {
        while (!stopping.load()) {
            if (!duplication) {
                if (SUCCEEDED(create_duplication())) { ++recreates; ++recoveries; }
                else { active.store(false); std::this_thread::sleep_for(std::chrono::milliseconds(250)); continue; }
            }
            DXGI_OUTDUPL_FRAME_INFO info{};
            ComPtr<IDXGIResource> resource;
            FrameLease lease(duplication.Get());
            HRESULT hr = duplication->AcquireNextFrame(100, &info, &resource);
            if (hr == DXGI_ERROR_WAIT_TIMEOUT) { ++timeouts; continue; }
            if (hr == DXGI_ERROR_ACCESS_LOST || hr == DXGI_ERROR_NOT_CURRENTLY_AVAILABLE || hr == DXGI_ERROR_INVALID_CALL) {
                access_lost.store(true); active.store(false); duplication.Reset(); continue;
            }
            if (FAILED(hr)) {
                if (device && FAILED(device->GetDeviceRemovedReason())) device_lost.store(true);
                active.store(false); duplication.Reset(); continue;
            }
            lease.acquired();
            ComPtr<ID3D11Texture2D> source;
            if (FAILED(resource.As(&source))) continue;
            D3D11_TEXTURE2D_DESC desc{}; source->GetDesc(&desc);
            if (FAILED(ensure_slots(desc))) continue;
            collect_metadata(info, desc.Width, desc.Height);

            // Desktop Duplication wakes for pointer-only changes too.  Snowlink
            // sends the cursor on its own low-latency channel, so publishing a
            // full desktop texture here would needlessly run GPU processing and
            // video encoding while the desktop itself is static.  The first
            // desktop image and every real dirty/move update have
            // AccumulatedFrames != 0 and continue through the normal path.
            if (info.AccumulatedFrames == 0) continue;
            {
                std::scoped_lock lock(mutex);
                if (published_id != materialized_id) {
                    // The prior publication was superseded before the consumer
                    // copied it. Return its keyed mutex to the producer instead
                    // of permanently stranding one of the two bounded slots.
                    const HRESULT stale = consumer_mutexes[published_slot]->AcquireSync(1, 0);
                    if (stale == S_OK) {
                        consumer_mutexes[published_slot]->ReleaseSync(0);
                        materialized_id = published_id;
                        ++replaced;
                    }
                }
                const uint32_t next = (published_slot + 1u) % 2u;
                const HRESULT sync = producer_mutexes[next]->AcquireSync(0, 0);
                if (sync == WAIT_TIMEOUT) { ++replaced; continue; }
                if (FAILED(sync)) { device_lost.store(true); continue; }
                context->CopyResource(slots[next].Get(), source.Get());
                producer_mutexes[next]->ReleaseSync(1);
                if (published_id && last_acquired.load() < published_id) ++replaced;
                published_slot = next; ++published_id; ++frames;
            }
        }
        active.store(false);
    }

    void close() noexcept {
        stopping.store(true);
        if (worker.joinable()) worker.join();
        std::scoped_lock lock(mutex);
        slots = {}; producer_mutexes = {}; consumer_shared_slots = {};
        consumer_mutexes = {}; consumer_slots = {}; duplication.Reset();
        consumer_context.Reset(); consumer_device.Reset(); context.Reset(); device.Reset();
    }
};

DxgiCaptureBackend::DxgiCaptureBackend() = default;
DxgiCaptureBackend::~DxgiCaptureBackend() { stop(); }

int32_t DxgiCaptureBackend::start(const CaptureConfig& config) {
    stop();
    auto impl = std::make_shared<Impl>(); impl->config = config;
    HRESULT hr = impl->create_duplication();
    if (FAILED(hr)) return static_cast<int32_t>(hr);
    impl->worker = std::thread([impl] { impl->run(); });
    impl_ = std::move(impl); return 0;
}

int32_t DxgiCaptureBackend::stop() { auto impl = std::move(impl_); if (impl) impl->close(); return 0; }

int32_t DxgiCaptureBackend::get_latest_frame(ID3D11Texture2D** texture, uint64_t* id,
                                              FrameMetadata* metadata, PointerState* pointer) const {
    if (!texture || !id) return kInvalidArgument;
    *texture = nullptr; *id = 0;
    auto impl = impl_; if (!impl) return kNotRunning;
    std::scoped_lock lock(impl->mutex);
    if (!impl->published_id || !impl->consumer_slots[0]) return kNoFrame;
    if (impl->materialized_id != impl->published_id) {
        const auto source_slot = impl->published_slot;
        const HRESULT sync = impl->consumer_mutexes[source_slot]->AcquireSync(1, 100);
        if (sync == WAIT_TIMEOUT) return kNoFrame;
        if (FAILED(sync)) return static_cast<int32_t>(sync);
        impl->consumer_slot = (impl->consumer_slot + 1u) % 2u;
        impl->consumer_context->CopyResource(
            impl->consumer_slots[impl->consumer_slot].Get(),
            impl->consumer_shared_slots[source_slot].Get());
        impl->consumer_mutexes[source_slot]->ReleaseSync(0);
        impl->materialized_id = impl->published_id;
    }
    impl->consumer_slots[impl->consumer_slot].CopyTo(texture); *id = impl->materialized_id;
    if (metadata) *metadata = impl->metadata;
    if (pointer) *pointer = impl->pointer;
    impl->last_acquired.store(*id); return 0;
}

int32_t DxgiCaptureBackend::set_capture_cursor_in_video(bool enabled) { return enabled ? -4 : 0; }

int32_t DxgiCaptureBackend::get_capture_status(CaptureStatus& status) const {
    status = {}; status.capture_border_active = false; status.backend = static_cast<int32_t>(CaptureBackend::Dxgi);
    auto impl = impl_; if (!impl) return 0;
    status.capture_active = impl->active.load(); status.access_lost = impl->access_lost.load();
    status.device_lost = impl->device_lost.load(); status.width = impl->width.load();
    status.height = impl->height.load(); status.rotation = static_cast<DXGI_MODE_ROTATION>(impl->rotation.load());
    return 0;
}

int32_t DxgiCaptureBackend::get_stats(CaptureBackendStats& stats) const {
    stats = {}; auto impl = impl_; if (!impl) return 0;
    stats.frames_captured = impl->frames.load(); stats.frames_replaced = impl->replaced.load();
    stats.frame_pool_recreates = impl->recreates.load(); stats.timeouts = impl->timeouts.load();
    stats.access_lost_recoveries = impl->recoveries.load(); stats.dirty_rects = impl->dirty_count.load();
    stats.move_rects = impl->move_count.load(); stats.pointer_updates = impl->pointer_count.load(); return 0;
}

} // namespace snowlink
