#include "snowlink/c_api.h"
#include "snowlink/engine.h"

#include <cstdint>
#include <exception>

using namespace snowlink;

const char* snowlink_engine_version() noexcept {
    return "snowlink_native_engine_foundation_0.1.0";
}

int32_t snowlink_engine_create(void** engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }

    try {
        auto* engine = new SnowlinkEngine();
        *engine_handle = static_cast<void*>(engine);
        return 0;
    } catch (const std::exception&) {
        return -1;
    }
}

int32_t snowlink_engine_destroy(void* engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    delete engine;
    return 0;
}

int32_t snowlink_engine_initialize(void* engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->initialize();
}

int32_t snowlink_engine_shutdown(void* engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->shutdown();
}

int32_t snowlink_engine_start_capture(void* engine_handle, const SnowlinkCaptureConfig* config) noexcept {
    if (!engine_handle || !config) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    CaptureConfig internal{};
    internal.monitor_index = config->monitor_index;
    internal.width = config->width;
    internal.height = config->height;
    internal.target_fps = config->target_fps;
    internal.backend = config->backend;
    internal.display_id = config->display_id;
    return engine->start_capture(internal);
}

int32_t snowlink_engine_stop_capture(void* engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->stop_capture();
}

int32_t snowlink_engine_start_stream(void* engine_handle, const SnowlinkStreamConfig* config) noexcept {
    if (!engine_handle || !config) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    StreamConfig internal{};
    internal.width = config->width;
    internal.height = config->height;
    internal.target_fps = config->target_fps;
    internal.bitrate_bps = config->bitrate_bps;
    return engine->start_stream(internal);
}

int32_t snowlink_engine_stop_stream(void* engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->stop_stream();
}

int32_t snowlink_engine_set_target_fps(void* engine_handle, int32_t target_fps) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->set_target_fps(target_fps);
}

int32_t snowlink_engine_set_bitrate(void* engine_handle, int32_t bitrate_bps) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->set_bitrate(bitrate_bps);
}

int32_t snowlink_engine_set_resolution(void* engine_handle, int32_t width, int32_t height) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->set_resolution(width, height);
}

int32_t snowlink_engine_request_keyframe(void* engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->request_keyframe();
}

int32_t snowlink_engine_set_capture_cursor_in_video(void* engine_handle, int32_t enabled) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->set_capture_cursor_in_video(enabled != 0);
}

int32_t snowlink_engine_get_capture_status(void* engine_handle, SnowlinkCaptureStatus* status) noexcept {
    if (!engine_handle || !status) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    CaptureStatus internal_status;
    int32_t result = engine->get_capture_status(internal_status);
    status->borderless_capture_available = internal_status.borderless_capture_available ? 1 : 0;
    status->borderless_capture_granted = internal_status.borderless_capture_granted ? 1 : 0;
    status->capture_border_active = internal_status.capture_border_active ? 1 : 0;
    status->capture_cursor_in_video = internal_status.capture_cursor_in_video ? 1 : 0;
    status->capture_active = internal_status.capture_active ? 1 : 0;
    status->access_lost = internal_status.access_lost ? 1 : 0;
    status->device_lost = internal_status.device_lost ? 1 : 0;
    status->width = internal_status.width;
    status->height = internal_status.height;
    return result;
}

int32_t snowlink_engine_get_stats(void* engine_handle, SnowlinkEngineStats* stats) noexcept {
    if (!engine_handle || !stats) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    EngineStats internal{};
    const int32_t result = engine->get_stats(internal);
    stats->capture_fps = internal.capture_fps;
    stats->encode_fps = internal.encode_fps;
    stats->render_fps = internal.render_fps;
    stats->bitrate_bps = internal.bitrate_bps;
    stats->frames_captured = internal.frames_captured;
    stats->frames_encoded = internal.frames_encoded;
    stats->frames_dropped = internal.frames_dropped;
    stats->frames_decoded = internal.frames_decoded;
    stats->capture_latency_ms = internal.capture_latency_ms;
    stats->encode_latency_ms = internal.encode_latency_ms;
    stats->decode_latency_ms = internal.decode_latency_ms;
    stats->render_latency_ms = internal.render_latency_ms;
    stats->network_rtt_ms = internal.network_rtt_ms;
    return result;
}

int32_t snowlink_engine_get_state(void* engine_handle) noexcept {
    if (!engine_handle) {
        return static_cast<int32_t>(EngineState::Uninitialized);
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return static_cast<int32_t>(engine->get_state());
}

const char* snowlink_engine_last_error(void* engine_handle) noexcept {
    if (!engine_handle) {
        return "invalid handle";
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->last_error().c_str();
}
