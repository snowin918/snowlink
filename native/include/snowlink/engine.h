#pragma once

#include "types.h"
#include "status_util.h"

#include <atomic>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <condition_variable>
#include <deque>
#include "encoder.h"
#include "input.h"

namespace snowlink {

class CaptureManager;
class IVideoEncoder;
class GpuFrameProcessor;
class IVideoDecoder;
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
    int32_t start_receiver(std::uint64_t hwnd, const TransportConfig& config);
    int32_t create_receiver_answer();
    int32_t stop_receiver();
    int32_t receiver_resize();
    int32_t receiver_set_visible(bool visible);
    int32_t send_remote_input(const RemoteInputEvent& event);
    int32_t set_remote_input_enabled(bool enabled);
    int32_t get_decoder_info(std::string& name, bool& hardware, std::uint32_t& width,
                             std::uint32_t& height, double& fps) const;

    int32_t set_target_fps(int32_t target_fps);
    int32_t set_bitrate(int32_t bitrate_bps);
    int32_t set_resolution(int32_t width, int32_t height);
    int32_t set_capture_cursor_in_video(bool enabled);
    int32_t get_capture_status(CaptureStatus& out_status) const;

    int32_t request_keyframe();

    int32_t get_stats(EngineStats& out_stats) const;
    EngineState get_state() const noexcept;
    std::string last_error() const noexcept;

private:
    static void transport_keyframe_request(void* context);
    static void transport_access_unit(void* context, const std::uint8_t* data, std::size_t size, std::uint64_t timestamp);
    static void transport_cursor_message(void* context,const std::uint8_t* data,std::size_t size);
    static void transport_input_message(void* context,const std::uint8_t* data,std::size_t size);
    void stream_loop(StreamConfig config);
    void receive_loop();
    void set_last_error(const char* message) noexcept;

    EngineState state_;
    EngineStats stats_;
    std::string last_error_;
    mutable std::mutex error_mutex_;

    std::unique_ptr<CaptureManager> capture_manager_;
    std::unique_ptr<IVideoEncoder> encoder_;
    std::unique_ptr<GpuFrameProcessor> processor_;
    std::unique_ptr<IVideoDecoder> decoder_;
    std::unique_ptr<Renderer> renderer_;
    std::unique_ptr<Transport> transport_;
    std::unique_ptr<CursorSubsystem> cursor_;
    std::unique_ptr<InputSubsystem> input_;
    mutable std::mutex stats_mutex_;
    std::thread stream_thread_;
    std::atomic<bool> stop_stream_requested_{false};
    std::thread receive_thread_;
    std::atomic<bool> stop_receive_requested_{false};
    mutable std::mutex receive_mutex_;
    std::condition_variable receive_wake_;
    std::deque<EncodedFrame> receive_queue_;
    std::uint64_t receive_frame_id_ = 0;
    bool awaiting_keyframe_ = true;
    bool remote_input_enabled_ = true;
    CaptureConfig capture_config_{};
};

} // namespace snowlink
