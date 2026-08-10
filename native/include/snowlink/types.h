#pragma once

#include <cstdint>
#include <vector>
#include <Windows.h>
#include <dxgi1_2.h>

namespace snowlink {

enum class CaptureBackend : std::int32_t { Auto = -1, Dxgi = 0, Wgc = 1 };

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
    std::int32_t backend = static_cast<std::int32_t>(CaptureBackend::Auto);
    std::uint64_t display_id = 0; // optional WinRT DisplayId when using WinRT backend
};

struct CaptureStatus {
    bool borderless_capture_available = false;
    bool borderless_capture_granted = false;
    bool capture_border_active = true;
    bool capture_cursor_in_video = false;
    bool capture_active = false;
    bool access_lost = false;
    bool device_lost = false;
    std::int32_t width = 0;
    std::int32_t height = 0;
    std::int32_t backend = static_cast<std::int32_t>(CaptureBackend::Auto);
    DXGI_MODE_ROTATION rotation = DXGI_MODE_ROTATION_UNSPECIFIED;
};

struct FrameMetadata {
    std::uint64_t timestamp_qpc = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::vector<RECT> dirty_rects;
    std::vector<DXGI_OUTDUPL_MOVE_RECT> move_rects;
    bool desktop_updated = false;
    bool pointer_updated = false;
};

struct PointerState {
    POINT position{};
    POINT hotspot{};
    bool visible = false;
    bool shape_changed = false;
    DXGI_OUTDUPL_POINTER_SHAPE_INFO shape_info{};
    std::vector<std::uint8_t> shape;
};

struct CaptureBackendStats {
    std::uint64_t frames_captured = 0;
    std::uint64_t frames_replaced = 0;
    std::uint64_t frame_pool_recreates = 0;
    std::uint64_t timeouts = 0;
    std::uint64_t access_lost_recoveries = 0;
    std::uint64_t dirty_rects = 0;
    std::uint64_t move_rects = 0;
    std::uint64_t pointer_updates = 0;
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
    double send_bitrate = 0.0;
    std::uint64_t packets_sent = 0;
    std::uint64_t packets_dropped = 0;
    std::uint64_t transport_frames_dropped = 0;
    std::uint64_t transport_errors = 0;
    std::uint32_t transport_queue_depth = 0;
    double estimated_loss = 0.0;
};

} // namespace snowlink
