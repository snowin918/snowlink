#include "snowlink/capture.h"
#include "snowlink/capture/wgc_capture_backend.h"
#include "snowlink/capture/dxgi_capture_backend.h"

#include <memory>

namespace snowlink {

class CaptureManager::State {
public:
    std::unique_ptr<ICaptureBackend> backend;
    bool cursor_in_video = false;
};

CaptureManager::CaptureManager() : state_(std::make_unique<State>()) {}
CaptureManager::~CaptureManager() { shutdown(); }

int32_t CaptureManager::initialize() { return 0; }
int32_t CaptureManager::shutdown() { return stop(); }

int32_t CaptureManager::start(const CaptureConfig& config) {
    stop();
    const auto requested = static_cast<CaptureBackend>(config.backend);
    auto try_start = [&](std::unique_ptr<ICaptureBackend> candidate) {
        candidate->set_capture_cursor_in_video(state_->cursor_in_video);
        const auto result = candidate->start(config);
        if (result == 0) state_->backend = std::move(candidate);
        return result;
    };
    if (requested == CaptureBackend::Wgc) return try_start(std::make_unique<WgcCaptureBackend>());
    if (requested == CaptureBackend::Dxgi) return try_start(std::make_unique<DxgiCaptureBackend>());
    if (requested != CaptureBackend::Auto) return -4;
    const auto wgc_result = try_start(std::make_unique<WgcCaptureBackend>());
    if (wgc_result == 0) return 0;
    return try_start(std::make_unique<DxgiCaptureBackend>());
}

int32_t CaptureManager::stop() {
    if (state_ && state_->backend) {
        state_->backend->stop();
        state_->backend.reset();
    }
    return 0;
}

int32_t CaptureManager::set_capture_cursor_in_video(bool enabled) {
    state_->cursor_in_video = enabled;
    return state_->backend ? state_->backend->set_capture_cursor_in_video(enabled) : 0;
}

int32_t CaptureManager::get_capture_status(CaptureStatus& status) const {
    status = {};
    status.capture_border_active = true;
    status.capture_cursor_in_video = state_->cursor_in_video;
    return state_->backend ? state_->backend->get_capture_status(status) : 0;
}

int32_t CaptureManager::get_stats(CaptureBackendStats& stats) const {
    stats = {};
    return state_->backend ? state_->backend->get_stats(stats) : 0;
}

int32_t CaptureManager::get_latest_frame(ID3D11Texture2D** texture, uint64_t* id,
                                         FrameMetadata* metadata, PointerState* pointer) const {
    if (!state_->backend) return -2;
    return state_->backend->get_latest_frame(texture, id, metadata, pointer);
}

} // namespace snowlink
