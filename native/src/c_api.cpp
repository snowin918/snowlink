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

int32_t snowlink_engine_start_capture(void* engine_handle, const CaptureConfig* config) noexcept {
    if (!engine_handle || !config) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->start_capture(*config);
}

int32_t snowlink_engine_stop_capture(void* engine_handle) noexcept {
    if (!engine_handle) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->stop_capture();
}

int32_t snowlink_engine_start_stream(void* engine_handle, const StreamConfig* config) noexcept {
    if (!engine_handle || !config) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->start_stream(*config);
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

int32_t snowlink_engine_get_stats(void* engine_handle, EngineStats* stats) noexcept {
    if (!engine_handle || !stats) {
        return -1;
    }
    auto* engine = static_cast<SnowlinkEngine*>(engine_handle);
    return engine->get_stats(*stats);
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
