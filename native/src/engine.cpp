#include "snowlink/engine.h"

#include "snowlink/capture.h"
#include "snowlink/encoder.h"
#include "snowlink/decoder.h"
#include "snowlink/renderer.h"
#include "snowlink/transport.h"
#include "snowlink/cursor.h"
#include "snowlink/input.h"

#include <utility>

namespace snowlink {

SnowlinkEngine::SnowlinkEngine()
    : state_(EngineState::Uninitialized), last_error_("") {
}

SnowlinkEngine::~SnowlinkEngine() {
    shutdown();
}

int32_t SnowlinkEngine::initialize() {
    if (state_ != EngineState::Uninitialized) {
        return static_cast<int32_t>(state_);
    }

    capture_manager_ = std::make_unique<CaptureManager>();
    encoder_ = std::make_unique<H264HardwareEncoder>();
    decoder_ = std::make_unique<Decoder>();
    renderer_ = std::make_unique<Renderer>();
    transport_ = std::make_unique<Transport>();
    cursor_ = std::make_unique<CursorSubsystem>();
    input_ = std::make_unique<InputSubsystem>();

    state_ = EngineState::Initialized;
    return 0;
}

int32_t SnowlinkEngine::shutdown() {
    if (state_ == EngineState::Shutdown || state_ == EngineState::Uninitialized) {
        return 0;
    }

    if (input_) {
        input_->shutdown();
    }
    if (cursor_) {
        cursor_->shutdown();
    }
    if (transport_) {
        transport_->shutdown();
    }
    if (renderer_) {
        renderer_->shutdown();
    }
    if (decoder_) {
        decoder_->shutdown();
    }
    if (encoder_) {
        encoder_->shutdown();
    }
    if (capture_manager_) {
        capture_manager_->shutdown();
    }

    state_ = EngineState::Shutdown;
    return 0;
}

int32_t SnowlinkEngine::start_capture(const CaptureConfig& config) {
    if (state_ != EngineState::Initialized) {
        set_last_error("Engine is not initialized.");
        return -1;
    }
    if (!capture_manager_) {
        set_last_error("Capture manager not initialized.");
        return -1;
    }

    int32_t res = capture_manager_->start(config);
    if (res != 0) {
        set_last_error("Failed to start capture");
        return res;
    }

    state_ = EngineState::Capturing;
    return 0;
}

int32_t SnowlinkEngine::stop_capture() {
    if (capture_manager_) {
        capture_manager_->stop();
    }
    state_ = EngineState::Initialized;
    return 0;
}

int32_t SnowlinkEngine::start_stream(const StreamConfig& config) {
    if (state_ != EngineState::Initialized) {
        set_last_error("Engine is not initialized.");
        return -1;
    }
    return -4;
}

int32_t SnowlinkEngine::stop_stream() {
    return 0;
}

int32_t SnowlinkEngine::set_target_fps(int32_t target_fps) {
    stats_.capture_fps = static_cast<double>(target_fps);
    return 0;
}

int32_t SnowlinkEngine::set_bitrate(int32_t bitrate_bps) {
    stats_.bitrate_bps = bitrate_bps;
    return 0;
}

int32_t SnowlinkEngine::set_resolution(int32_t width, int32_t height) {
    return 0;
}

int32_t SnowlinkEngine::set_capture_cursor_in_video(bool enabled) {
    if (!capture_manager_) {
        set_last_error("Capture manager not initialized.");
        return -1;
    }
    return capture_manager_->set_capture_cursor_in_video(enabled);
}

int32_t SnowlinkEngine::get_capture_status(CaptureStatus& out_status) const {
    if (!capture_manager_) {
        return -1;
    }
    return capture_manager_->get_capture_status(out_status);
}

int32_t SnowlinkEngine::request_keyframe() {
    return -4;
}

int32_t SnowlinkEngine::get_stats(EngineStats& out_stats) const {
    out_stats = stats_;
    if (capture_manager_) {
        CaptureBackendStats capture_stats{};
        if (capture_manager_->get_stats(capture_stats) == 0) {
            out_stats.frames_captured = capture_stats.frames_captured;
            out_stats.frames_dropped = capture_stats.frames_replaced;
        }
    }
    return 0;
}

EngineState SnowlinkEngine::get_state() const noexcept {
    return state_;
}

const std::string& SnowlinkEngine::last_error() const noexcept {
    return last_error_;
}

void SnowlinkEngine::set_last_error(const char* message) noexcept {
    last_error_ = message ? message : "";
}

} // namespace snowlink
