#pragma once

#include "types.h"
#include "status_util.h"

#include <atomic>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace snowlink {

class CaptureManager;
class IVideoEncoder;
class GpuFrameProcessor;
class Decoder;
class Renderer;
class Transport;
struct TransportConfig;
class CursorSubsystem;
class InputSubsystem;

class SnowlinkEngine {
public:
    SnowlinkEngine();
    ~SnowlinkEngine();

    int32_t initialize();
    int32_t shutdown();

    int32_t start_capture(const CaptureConfig& config);
    int32_t stop_capture();

    int32_t start_stream(const StreamConfig& config);
    int32_t stop_stream();

    int32_t connect_transport(const TransportConfig& config);
    int32_t create_transport_offer();
    int32_t get_transport_local_description(std::string& sdp, std::string& type) const;
    int32_t set_transport_remote_description(const std::string& sdp, const std::string& type);

    int32_t set_target_fps(int32_t target_fps);
    int32_t set_bitrate(int32_t bitrate_bps);
    int32_t set_resolution(int32_t width, int32_t height);
    int32_t set_capture_cursor_in_video(bool enabled);
    int32_t get_capture_status(CaptureStatus& out_status) const;

    int32_t request_keyframe();

    int32_t get_stats(EngineStats& out_stats) const;
    EngineState get_state() const noexcept;
    const std::string& last_error() const noexcept;

private:
    static void transport_keyframe_request(void* context);
    void stream_loop(StreamConfig config);
    void set_last_error(const char* message) noexcept;

    EngineState state_;
    EngineStats stats_;
    std::string last_error_;

    std::unique_ptr<CaptureManager> capture_manager_;
    std::unique_ptr<IVideoEncoder> encoder_;
    std::unique_ptr<GpuFrameProcessor> processor_;
    std::unique_ptr<Decoder> decoder_;
    std::unique_ptr<Renderer> renderer_;
    std::unique_ptr<Transport> transport_;
    std::unique_ptr<CursorSubsystem> cursor_;
    std::unique_ptr<InputSubsystem> input_;
    mutable std::mutex stats_mutex_;
    std::thread stream_thread_;
    std::atomic<bool> stop_stream_requested_{false};
};

} // namespace snowlink
