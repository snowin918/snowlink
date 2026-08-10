#pragma once

#include <cstdint>

#ifdef _WIN32
    #define SNOWLINK_API __declspec(dllexport)
#else
    #define SNOWLINK_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct SnowlinkCaptureConfig {
    int32_t monitor_index;
    int32_t width;
    int32_t height;
    int32_t target_fps;
    int32_t backend;
    uint64_t display_id;
} SnowlinkCaptureConfig;

typedef struct SnowlinkStreamConfig {
    int32_t width;
    int32_t height;
    int32_t target_fps;
    int32_t bitrate_bps;
} SnowlinkStreamConfig;

typedef struct SnowlinkTransportConfig {
    const char* bind_address;
    uint16_t port_min;
    uint16_t port_max;
    uint32_t mtu;
    uint32_t frame_queue_limit;
    uint32_t nack_packet_limit;
} SnowlinkTransportConfig;
typedef struct SnowlinkInputEvent {
    uint8_t kind, code, down, reserved;
    int32_t x, y, delta;
    uint64_t sequence;
} SnowlinkInputEvent;

typedef struct SnowlinkEngineStats {
    double capture_fps;
    double encode_fps;
    double decode_fps;
    double render_fps;
    int64_t bitrate_bps;
    uint64_t frames_captured;
    uint64_t frames_encoded;
    uint64_t frames_dropped;
    uint64_t frames_decoded;
    double capture_latency_ms;
    double encode_latency_ms;
    double decode_latency_ms;
    double render_latency_ms;
    double network_rtt_ms;
    double send_bitrate;
    uint64_t packets_sent;
    uint64_t packets_dropped;
    uint64_t transport_frames_dropped;
    uint64_t transport_errors;
    uint32_t transport_queue_depth;
    double estimated_loss;
} SnowlinkEngineStats;

typedef struct SnowlinkCaptureStatus {
    int32_t borderless_capture_available;
    int32_t borderless_capture_granted;
    int32_t capture_border_active;
    int32_t capture_cursor_in_video;
    int32_t capture_active;
    int32_t access_lost;
    int32_t device_lost;
    int32_t width;
    int32_t height;
} SnowlinkCaptureStatus;

SNOWLINK_API const char* snowlink_engine_version() noexcept;
SNOWLINK_API int32_t snowlink_engine_create(void** engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_destroy(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_initialize(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_shutdown(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_start_capture(void* engine_handle, const SnowlinkCaptureConfig* config) noexcept;
SNOWLINK_API int32_t snowlink_engine_stop_capture(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_start_stream(void* engine_handle, const SnowlinkStreamConfig* config) noexcept;
SNOWLINK_API int32_t snowlink_engine_stop_stream(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_connect_transport(void* engine_handle, const SnowlinkTransportConfig* config) noexcept;
SNOWLINK_API int32_t snowlink_engine_create_transport_offer(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_get_local_sdp(void* engine_handle, char* buffer, uint32_t buffer_size) noexcept;
SNOWLINK_API int32_t snowlink_engine_get_local_sdp_type(void* engine_handle, char* buffer, uint32_t buffer_size) noexcept;
SNOWLINK_API int32_t snowlink_engine_set_remote_sdp(void* engine_handle, const char* sdp, const char* type) noexcept;
SNOWLINK_API int32_t snowlink_engine_start_receiver(void* engine_handle, uint64_t hwnd, const SnowlinkTransportConfig* config) noexcept;
SNOWLINK_API int32_t snowlink_engine_create_receiver_answer(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_stop_receiver(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_receiver_resize(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_receiver_set_visible(void* engine_handle, int32_t visible) noexcept;
SNOWLINK_API int32_t snowlink_engine_send_input(void* engine_handle, const SnowlinkInputEvent* event) noexcept;
SNOWLINK_API int32_t snowlink_engine_set_remote_input_enabled(void* engine_handle, int32_t enabled) noexcept;
SNOWLINK_API int32_t snowlink_engine_get_decoder_name(void* engine_handle, char* buffer, uint32_t buffer_size) noexcept;
SNOWLINK_API int32_t snowlink_engine_get_decoder_status(void* engine_handle, int32_t* hardware, uint32_t* width, uint32_t* height, double* fps) noexcept;
SNOWLINK_API int32_t snowlink_engine_set_target_fps(void* engine_handle, int32_t target_fps) noexcept;
SNOWLINK_API int32_t snowlink_engine_set_bitrate(void* engine_handle, int32_t bitrate_bps) noexcept;
SNOWLINK_API int32_t snowlink_engine_set_resolution(void* engine_handle, int32_t width, int32_t height) noexcept;
SNOWLINK_API int32_t snowlink_engine_request_keyframe(void* engine_handle) noexcept;
SNOWLINK_API int32_t snowlink_engine_set_capture_cursor_in_video(void* engine_handle, int32_t enabled) noexcept;
SNOWLINK_API int32_t snowlink_engine_get_capture_status(void* engine_handle, SnowlinkCaptureStatus* status) noexcept;
SNOWLINK_API int32_t snowlink_engine_get_stats(void* engine_handle, SnowlinkEngineStats* stats) noexcept;
SNOWLINK_API int32_t snowlink_engine_get_state(void* engine_handle) noexcept;
SNOWLINK_API const char* snowlink_engine_last_error(void* engine_handle) noexcept;

#ifdef __cplusplus
}
#endif
