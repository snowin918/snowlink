#pragma once

#include <cstdint>

namespace snowlink {

enum class EngineState : std::int32_t {
    Uninitialized = 0,
    Initialized = 1,
    Capturing = 2,
    Streaming = 3,
    Shutdown = 4,
};

struct CaptureConfig {
    std::int32_t monitor_index = 0;
    std::int32_t width = 0;
    std::int32_t height = 0;
    std::int32_t target_fps = 0;
    std::int32_t backend = 0; // 0 = DXGI, 1 = WinRT
};

struct StreamConfig {
    std::int32_t width = 0;
    std::int32_t height = 0;
    std::int32_t target_fps = 0;
    std::int32_t bitrate_bps = 0;
};

struct EngineStats {
    double capture_fps = 0.0;
    double encode_fps = 0.0;
    double render_fps = 0.0;
    std::int64_t bitrate_bps = 0;
    std::uint64_t frames_captured = 0;
    std::uint64_t frames_encoded = 0;
    std::uint64_t frames_dropped = 0;
    std::uint64_t frames_decoded = 0;
    double capture_latency_ms = 0.0;
    double encode_latency_ms = 0.0;
    double decode_latency_ms = 0.0;
    double render_latency_ms = 0.0;
    double network_rtt_ms = 0.0;
};

} // namespace snowlink
