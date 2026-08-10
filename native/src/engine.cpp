#include "snowlink/engine.h"

#include "snowlink/capture.h"
#include "snowlink/encoder.h"
#include "snowlink/decoder.h"
#include "snowlink/renderer.h"
#include "snowlink/transport.h"
#include "snowlink/cursor.h"
#include "snowlink/input.h"
#include "snowlink/gpu_frame_processor.h"

#include <chrono>
#include <vector>
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
    processor_ = std::make_unique<GpuFrameProcessor>();
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

    stop_stream();
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
    stop_stream();
    if (capture_manager_) {
        capture_manager_->stop();
    }
    state_ = EngineState::Initialized;
    return 0;
}

int32_t SnowlinkEngine::start_stream(const StreamConfig& config) {
    if (state_ != EngineState::Capturing || !capture_manager_ || !processor_ || !encoder_ || !transport_) {
        set_last_error("Capture and native transport must be initialized before streaming.");
        return -1;
    }
    if (config.width <= 0 || config.height <= 0 || (config.width & 1) ||
        (config.height & 1) || config.target_fps <= 0 || config.bitrate_bps <= 0) {
        set_last_error("Invalid stream dimensions, frame rate, or bitrate.");
        return -1;
    }
    TransportStats transport_stats{};
    transport_->get_stats(transport_stats);
    if (!transport_stats.connected) {
        set_last_error("WebRTC transport is not connected.");
        return -2;
    }
    GpuFrameProcessorConfig processor_config{};
    processor_config.target_width = static_cast<std::uint32_t>(config.width);
    processor_config.target_height = static_cast<std::uint32_t>(config.height);
    const int32_t result = processor_->configure(processor_config);
    if (result != 0) return result;
    stop_stream_requested_ = false;
    state_ = EngineState::Streaming;
    stream_thread_ = std::thread([this, config] { stream_loop(config); });
    return 0;
}

int32_t SnowlinkEngine::stop_stream() {
    stop_stream_requested_ = true;
    if (stream_thread_.joinable()) stream_thread_.join();
    if (encoder_) encoder_->shutdown();
    if (processor_) processor_->reset();
    if (state_ == EngineState::Streaming) state_ = EngineState::Capturing;
    return 0;
}

int32_t SnowlinkEngine::connect_transport(const TransportConfig& config) {
    if (!transport_ || (state_ != EngineState::Initialized && state_ != EngineState::Capturing)) return -1;
    return transport_->initialize(config, &SnowlinkEngine::transport_keyframe_request, this);
}

int32_t SnowlinkEngine::create_transport_offer() {
    return transport_ ? transport_->create_offer() : -1;
}

int32_t SnowlinkEngine::get_transport_local_description(std::string& sdp, std::string& type) const {
    return transport_ ? transport_->get_local_description(sdp, type) : -1;
}

int32_t SnowlinkEngine::set_transport_remote_description(const std::string& sdp,
                                                         const std::string& type) {
    return transport_ ? transport_->set_remote_description(sdp, type) : -1;
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
    return encoder_ ? encoder_->request_keyframe() : -1;
}

int32_t SnowlinkEngine::get_stats(EngineStats& out_stats) const {
    { std::lock_guard lock(stats_mutex_); out_stats = stats_; }
    if (capture_manager_) {
        CaptureBackendStats capture_stats{};
        if (capture_manager_->get_stats(capture_stats) == 0) {
            out_stats.frames_captured = capture_stats.frames_captured;
            out_stats.frames_dropped = capture_stats.frames_replaced;
        }
    }
    if (transport_) {
        TransportStats transport_stats{};
        transport_->get_stats(transport_stats);
        out_stats.send_bitrate = transport_stats.send_bitrate;
        out_stats.packets_sent = transport_stats.packets_sent;
        out_stats.packets_dropped = transport_stats.packets_dropped;
        out_stats.transport_frames_dropped = transport_stats.frames_dropped;
        out_stats.transport_queue_depth = transport_stats.queue_depth;
        out_stats.network_rtt_ms = transport_stats.rtt;
        out_stats.estimated_loss = transport_stats.estimated_loss;
        out_stats.transport_errors = transport_stats.transport_errors;
    }
    return 0;
}

void SnowlinkEngine::transport_keyframe_request(void* context) {
    if (context) static_cast<SnowlinkEngine*>(context)->request_keyframe();
}

void SnowlinkEngine::stream_loop(StreamConfig config) {
    std::uint64_t last_id = 0;
    bool encoder_ready = false;
    const auto epoch = std::chrono::steady_clock::now();
    while (!stop_stream_requested_) {
        ID3D11Texture2D* capture_texture = nullptr;
        std::uint64_t frame_id = 0;
        if (capture_manager_->get_latest_frame(&capture_texture, &frame_id) != 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }
        if (frame_id == last_id) {
            capture_texture->Release();
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }
        last_id = frame_id;
        CaptureStatus capture_status{};
        capture_manager_->get_capture_status(capture_status);
        GpuFrameProcessorConfig processor_config{};
        processor_config.target_width = static_cast<std::uint32_t>(config.width);
        processor_config.target_height = static_cast<std::uint32_t>(config.height);
        processor_config.rotation = capture_status.rotation;
        processor_->configure(processor_config);
        int32_t result = processor_->process_frame(capture_texture, frame_id);
        capture_texture->Release();
        ID3D11Texture2D* nv12 = nullptr;
        std::uint64_t processed_id = 0;
        if (result == 0) result = processor_->get_latest_frame(&nv12, &processed_id);
        if (result == 0 && !encoder_ready) {
            ID3D11Device* device = nullptr;
            nv12->GetDevice(&device);
            EncoderSettings settings{};
            settings.width = static_cast<std::uint32_t>(config.width);
            settings.height = static_cast<std::uint32_t>(config.height);
            settings.fps = static_cast<std::uint32_t>(config.target_fps);
            settings.bitrate = static_cast<std::uint32_t>(config.bitrate_bps);
            settings.keyframe_interval = static_cast<std::uint32_t>(config.target_fps * 2);
            result = encoder_->initialize(device, settings);
            device->Release();
            encoder_ready = result == 0;
        }
        if (result == 0 && encoder_ready) {
            std::vector<EncodedFrame> frames;
            const auto timestamp = std::chrono::duration_cast<
                std::chrono::duration<std::uint64_t, std::ratio<1, 10'000'000>>>(
                    std::chrono::steady_clock::now() - epoch).count();
            result = encoder_->encode(nv12, timestamp, frames);
            if (result == S_FALSE) {
                std::lock_guard lock(stats_mutex_); ++stats_.frames_dropped;
                result = 0;
            }
            for (auto& frame : frames) {
                if (transport_->enqueue(std::move(frame)) == 0) {
                    std::lock_guard lock(stats_mutex_); ++stats_.frames_encoded;
                }
            }
        }
        if (nv12) nv12->Release();
        if (result < 0) {
            std::lock_guard lock(stats_mutex_);
            ++stats_.frames_dropped;
        }
    }
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
