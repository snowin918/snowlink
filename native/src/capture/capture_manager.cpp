#include "snowlink/capture.h"
#include "snowlink/capture/wgc_capture_backend.h"

#include <memory>

namespace snowlink {

class CaptureManager::State {
public:
    std::unique_ptr<WgcCaptureBackend> wgc;
    bool cursor_in_video = false;
};

CaptureManager::CaptureManager() : state_(std::make_unique<State>()) {}
CaptureManager::~CaptureManager() { shutdown(); }

int32_t CaptureManager::initialize() { return 0; }
int32_t CaptureManager::shutdown() { return stop(); }

int32_t CaptureManager::start(const CaptureConfig& config) {
    stop();
    // Native backend 1 is Windows.Graphics.Capture. Backend 0 remains reserved
    // for the next-phase Desktop Duplication implementation.
    if (config.backend != 1) return -4;
    auto backend = std::make_unique<WgcCaptureBackend>();
    backend->set_capture_cursor_in_video(state_->cursor_in_video);
    const auto result = backend->start(config);
    if (result != 0) return result;
    state_->wgc = std::move(backend);
    return 0;
}

int32_t CaptureManager::stop() {
    if (state_ && state_->wgc) {
        state_->wgc->stop();
        state_->wgc.reset();
    }
    return 0;
}

int32_t CaptureManager::set_capture_cursor_in_video(bool enabled) {
    state_->cursor_in_video = enabled;
    return state_->wgc ? state_->wgc->set_capture_cursor_in_video(enabled) : 0;
}

int32_t CaptureManager::get_capture_status(CaptureStatus& status) const {
    status = {};
    status.capture_border_active = true;
    status.capture_cursor_in_video = state_->cursor_in_video;
    return state_->wgc ? state_->wgc->get_capture_status(status) : 0;
}

int32_t CaptureManager::get_stats(CaptureBackendStats& stats) const {
    stats = {};
    return state_->wgc ? state_->wgc->get_stats(stats) : 0;
}

} // namespace snowlink
