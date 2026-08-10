#include "snowlink/engine.h"

#include "snowlink/capture.h"
#include "snowlink/encoder.h"
#include "snowlink/decoder.h"
#include "snowlink/renderer.h"
#include "snowlink/transport.h"
#include "snowlink/cursor.h"
#include "snowlink/input.h"
#include "snowlink/gpu_frame_processor.h"
#include "snowlink/h264_bitstream.h"

#include <chrono>
#include <cstdio>
#include <vector>
#include <utility>
#include <d3d11.h>
#include <algorithm>
#include <wrl/client.h>

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
    decoder_ = std::make_unique<H264HardwareDecoder>();
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

    stop_receiver();
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
    capture_config_=config;
    struct Find{int wanted,current=0;RECT rect{};bool found=false;} find{config.monitor_index};
    EnumDisplayMonitors(nullptr,nullptr,[](HMONITOR,HDC,RECT*r,LPARAM p)->BOOL{auto&f=*reinterpret_cast<Find*>(p);if(f.current++==f.wanted){f.rect=*r;f.found=true;return FALSE;}return TRUE;},reinterpret_cast<LPARAM>(&find));
    RECT desktop=find.found?find.rect:RECT{0,0,config.width,config.height};
    input_->initialize();input_->set_source_desktop(desktop.left,desktop.top,desktop.right-desktop.left,desktop.bottom-desktop.top);
    cursor_->initialize_sender(desktop,[this](const CursorState&s){if(transport_)transport_->send_cursor(encode_cursor_state(s),false);},[this](const CursorShape&s){if(transport_)transport_->send_cursor(encode_cursor_shape(s),true);});
    return 0;
}

int32_t SnowlinkEngine::stop_capture() {
    stop_stream();
    if(input_)input_->set_authorized(false);
    if(cursor_)cursor_->shutdown();
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
    input_->set_authorized(remote_input_enabled_);
    state_ = EngineState::Streaming;
    stream_thread_ = std::thread([this, config] { stream_loop(config); });
    return 0;
}

int32_t SnowlinkEngine::stop_stream() {
    if(input_)input_->set_authorized(false);
    stop_stream_requested_ = true;
    if (stream_thread_.joinable()) stream_thread_.join();
    if (encoder_) encoder_->shutdown();
    if (processor_) processor_->reset();
    if (state_ == EngineState::Streaming) state_ = EngineState::Capturing;
    return 0;
}

int32_t SnowlinkEngine::set_remote_input_enabled(bool enabled) {
    remote_input_enabled_ = enabled;
    if (input_) input_->set_authorized(enabled && state_ == EngineState::Streaming);
    return 0;
}

int32_t SnowlinkEngine::connect_transport(const TransportConfig& config) {
    if (!transport_ || (state_ != EngineState::Initialized && state_ != EngineState::Capturing)) return -1;
    return transport_->initialize(config, &SnowlinkEngine::transport_keyframe_request, this,
                                  &SnowlinkEngine::transport_input_message, this);
}

int32_t SnowlinkEngine::create_transport_offer() {
    return transport_ ? transport_->create_offer() : -1;
}

int32_t SnowlinkEngine::get_transport_local_description(std::string& sdp, std::string& type) const {
    return transport_ ? transport_->get_local_description(sdp, type) : -1;
}

int32_t SnowlinkEngine::set_transport_remote_description(const std::string& sdp,
                                                         const std::string& type) {
    if(!transport_)return -1;
    const auto result=transport_->set_remote_description(sdp,type);
    return result;
}

int32_t SnowlinkEngine::start_receiver(std::uint64_t hwnd_value, const TransportConfig& config) {
    if (state_ != EngineState::Initialized || !decoder_ || !renderer_ || !transport_) return -1;
    HWND hwnd=reinterpret_cast<HWND>(static_cast<std::uintptr_t>(hwnd_value)); if(!IsWindow(hwnd))return -2;
    UINT flags=D3D11_CREATE_DEVICE_BGRA_SUPPORT|D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
    D3D_FEATURE_LEVEL levels[]={D3D_FEATURE_LEVEL_11_1,D3D_FEATURE_LEVEL_11_0}; D3D_FEATURE_LEVEL level{};
    Microsoft::WRL::ComPtr<ID3D11Device> device; Microsoft::WRL::ComPtr<ID3D11DeviceContext> context;
    HRESULT hr=D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,flags,levels,ARRAYSIZE(levels),D3D11_SDK_VERSION,&device,&level,&context);
    if(FAILED(hr))return hr;
    int32_t result=decoder_->initialize(device.Get()); if(result!=0)return result;
    result=renderer_->initialize(hwnd,device.Get()); if(result!=0){decoder_->shutdown();return result;}
    result=transport_->initialize_receiver(config,&SnowlinkEngine::transport_access_unit,this,
                                           &SnowlinkEngine::transport_cursor_message,this);
    if(result!=0){renderer_->shutdown();decoder_->shutdown();return result;}
    cursor_->initialize_receiver(hwnd,1,1);stop_receive_requested_=false;awaiting_keyframe_=true;receive_thread_=std::thread([this]{receive_loop();});return 0;
}
int32_t SnowlinkEngine::create_receiver_answer(){return transport_?transport_->create_answer():-1;}
int32_t SnowlinkEngine::stop_receiver(){stop_receive_requested_=true;receive_wake_.notify_all();if(receive_thread_.joinable())receive_thread_.join();{std::lock_guard lock(receive_mutex_);receive_queue_.clear();}if(cursor_)cursor_->shutdown();if(transport_)transport_->shutdown();if(renderer_)renderer_->shutdown();if(decoder_)decoder_->shutdown();return 0;}
int32_t SnowlinkEngine::receiver_resize(){return renderer_?renderer_->resize():-1;}
int32_t SnowlinkEngine::receiver_set_visible(bool v){return renderer_?renderer_->set_visible(v):-1;}
int32_t SnowlinkEngine::send_remote_input(const RemoteInputEvent&e){return transport_?transport_->send_input(encode_input_event(e)):-1;}
int32_t SnowlinkEngine::get_decoder_info(std::string& name,bool& hw,std::uint32_t& w,std::uint32_t& h,double& fps)const{if(!decoder_)return -1;const auto&i=decoder_->info();name=i.decoder_name;hw=i.hardware_accelerated;w=i.decoded_width;h=i.decoded_height;fps=i.decode_fps;return 0;}

void SnowlinkEngine::transport_access_unit(void* context,const std::uint8_t* data,std::size_t size,std::uint64_t timestamp){
    if(!context||!data||!size)return;auto*self=static_cast<SnowlinkEngine*>(context);EncodedFrame frame;frame.timestamp=timestamp;frame.bytes.assign(data,data+size);
    frame.keyframe=inspect_h264_access_unit(frame.bytes).has_idr;
    std::lock_guard lock(self->receive_mutex_);if(self->receive_queue_.size()>=2){self->receive_queue_.pop_front();++self->stats_.frames_dropped;}self->receive_queue_.push_back(std::move(frame));self->receive_wake_.notify_one();
}
void SnowlinkEngine::transport_cursor_message(void* context,const std::uint8_t*data,std::size_t size){if(!context)return;CursorState s;CursorShape shape;if(decode_cursor_message(data,size,&s,&shape)){auto*self=static_cast<SnowlinkEngine*>(context);if(size>1&&data[1]==1)self->cursor_->receive_state(s);else self->cursor_->receive_shape(shape);}}
void SnowlinkEngine::transport_input_message(void* context,const std::uint8_t*data,std::size_t size){if(!context)return;RemoteInputEvent event;if(decode_input_event(data,size,event))static_cast<SnowlinkEngine*>(context)->input_->inject(event);}
void SnowlinkEngine::receive_loop(){auto last_keyframe_request=std::chrono::steady_clock::time_point{};while(!stop_receive_requested_){EncodedFrame frame;{std::unique_lock lock(receive_mutex_);receive_wake_.wait(lock,[&]{return stop_receive_requested_||!receive_queue_.empty();});if(stop_receive_requested_)break;frame=std::move(receive_queue_.back());receive_queue_.clear();}
    if(awaiting_keyframe_&&!frame.keyframe){
        const auto bitstream=inspect_h264_access_unit(frame.bytes);char message[160]{};
        std::snprintf(message,sizeof(message),"Waiting for IDR: bytes=%zu sps=%d pps=%d.",frame.bytes.size(),bitstream.has_sps?1:0,bitstream.has_pps?1:0);set_last_error(message);
        const auto now=std::chrono::steady_clock::now();if(last_keyframe_request.time_since_epoch().count()==0||now-last_keyframe_request>=std::chrono::milliseconds(500)){transport_->request_remote_keyframe();last_keyframe_request=now;}std::lock_guard lock(stats_mutex_);++stats_.frames_dropped;continue;}ID3D11Texture2D* texture=nullptr;std::uint32_t subresource=0;int32_t result=decoder_->decode(frame,&texture,&subresource);
    if(result==S_FALSE){const auto bitstream=inspect_h264_access_unit(frame.bytes);char message[180]{};std::snprintf(message,sizeof(message),"Decoder needs input: bytes=%zu idr=%d sps=%d pps=%d.",frame.bytes.size(),bitstream.has_idr?1:0,bitstream.has_sps?1:0,bitstream.has_pps?1:0);set_last_error(message);}
    if(result<0){
        char message[96]{};
        std::snprintf(message, sizeof(message),
                      "H.264 decoder rejected access unit (HRESULT 0x%08X).",
                      static_cast<unsigned int>(result));
        set_last_error(message);
        awaiting_keyframe_=true;decoder_->reset();transport_->request_remote_keyframe();std::lock_guard lock(stats_mutex_);++stats_.frames_dropped;continue;
    }
    if(frame.keyframe)awaiting_keyframe_=false;if(texture){D3D11_TEXTURE2D_DESC d{};texture->GetDesc(&d);cursor_->update_source_size(d.Width,d.Height);renderer_->submit(texture,subresource,++receive_frame_id_);texture->Release();std::lock_guard lock(stats_mutex_);++stats_.frames_decoded;}
}}

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
            out_stats.frames_dropped += capture_stats.frames_replaced;
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
    if (decoder_) {
        const auto& decoder_info = decoder_->info();
        out_stats.decode_fps = decoder_info.decode_fps;
        out_stats.frames_decoded = decoder_info.frames_decoded;
    }
    if (renderer_) {
        RendererStats renderer_stats{};
        renderer_->get_stats(renderer_stats);
        out_stats.render_fps = renderer_stats.render_fps;
    }
    return 0;
}

void SnowlinkEngine::transport_keyframe_request(void* context) {
    if (context) static_cast<SnowlinkEngine*>(context)->request_keyframe();
}

void SnowlinkEngine::stream_loop(StreamConfig config) {
    std::uint64_t last_id = 0;
    bool encoder_ready = false;
    bool encoder_failed = false;
    const auto epoch = std::chrono::steady_clock::now();
    auto rate_mark = epoch;
    std::uint64_t rate_capture_frames = 0;
    std::uint64_t rate_encoded_frames = 0;
    bool logged_first_access_unit = false;
    const auto frame_interval = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
        std::chrono::duration<double>(1.0 / static_cast<double>(config.target_fps)));
    auto next_submit = epoch;
    auto publish_frames = [this, &rate_encoded_frames, &logged_first_access_unit](std::vector<EncodedFrame>& frames) {
        for (auto& frame : frames) {
            if (!logged_first_access_unit || frame.keyframe) {
                const auto bitstream = inspect_h264_access_unit(frame.bytes);
                char message[180]{};
                std::snprintf(message, sizeof(message),
                              "Encoded AU: bytes=%zu key=%d idr=%d sps=%d pps=%d.",
                              frame.bytes.size(), frame.keyframe ? 1 : 0,
                              bitstream.has_idr ? 1 : 0, bitstream.has_sps ? 1 : 0,
                              bitstream.has_pps ? 1 : 0);
                set_last_error(message);
                logged_first_access_unit = true;
            }
            if (transport_->enqueue(std::move(frame)) == 0) {
                ++rate_encoded_frames;
                std::lock_guard lock(stats_mutex_); ++stats_.frames_encoded;
            }
        }
    };
    while (!stop_stream_requested_) {
        if (encoder_ready) {
            std::vector<EncodedFrame> ready;
            const int32_t poll_result = encoder_->poll(ready);
            publish_frames(ready);
            if (poll_result < 0) {
                std::lock_guard lock(stats_mutex_); ++stats_.frames_dropped;
            }
        }
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
        const auto now = std::chrono::steady_clock::now();
        if (now < next_submit) {
            // Do not consume this ID yet. Re-reading the latest slot at the
            // deadline naturally coalesces any intervening capture frames.
            capture_texture->Release();
            const auto remaining = next_submit - now;
            std::this_thread::sleep_for(std::min(
                remaining, std::chrono::steady_clock::duration(std::chrono::milliseconds(1))));
            continue;
        }
        last_id = frame_id;
        ++rate_capture_frames;
        // Preserve cadence across ordinary Windows timer overshoot instead of
        // scheduling from a late wake and accumulating that lateness forever.
        // If the desktop was static for a whole interval, reset once rather
        // than emitting a catch-up burst.
        next_submit += frame_interval;
        if (next_submit <= now) next_submit = now + frame_interval;
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
        if (result != 0) {
            char message[96]{};
            std::snprintf(message, sizeof(message),
                          "GPU frame processing failed (HRESULT 0x%08X).",
                          static_cast<unsigned int>(result));
            set_last_error(message);
        }
        if (result == 0) {
            result = processor_->get_latest_frame(&nv12, &processed_id);
            if (result != 0) {
                char message[96]{};
                std::snprintf(message, sizeof(message),
                              "GPU processed-frame retrieval failed (HRESULT 0x%08X).",
                              static_cast<unsigned int>(result));
                set_last_error(message);
            }
        }
        if (result == 0 && !encoder_ready && !encoder_failed) {
            ID3D11Device* device = nullptr;
            nv12->GetDevice(&device);
            EncoderSettings settings{};
            settings.width = static_cast<std::uint32_t>(config.width);
            settings.height = static_cast<std::uint32_t>(config.height);
            settings.fps = static_cast<std::uint32_t>(config.target_fps);
            settings.bitrate = static_cast<std::uint32_t>(config.bitrate_bps);
            settings.keyframe_interval = static_cast<std::uint32_t>(config.target_fps * 2);
            settings.hardware_preference = HardwarePreference::AllowSoftwareFallback;
            result = encoder_->initialize(device, settings);
            device->Release();
            encoder_ready = result == 0;
            if (encoder_ready) {
                // The receiver deliberately ignores inter frames until it has
                // an IDR. Some software MFTs do not make their first sample a
                // clean point unless explicitly requested.
                (void)encoder_->request_keyframe();
            }
            if (!encoder_ready) {
                encoder_failed = true;
                const auto& encoder_info = encoder_->info();
                char message[192]{};
                std::snprintf(message, sizeof(message),
                              "H.264 encoder initialization failed at %s using %s "
                              "(HRESULT 0x%08X).",
                              encoder_info.failure_stage.empty() ? "unknown stage" :
                                  encoder_info.failure_stage.c_str(),
                              encoder_info.encoder_name.empty() ? "unknown encoder" :
                                  encoder_info.encoder_name.c_str(),
                              static_cast<unsigned int>(result));
                set_last_error(message);
            }
        }
        if (result == 0 && encoder_failed) {
            // Initialization failures are deterministic for this stream
            // configuration. Do not hammer the driver and starve the UI by
            // retrying on every captured frame.
            result = E_FAIL;
        }
        if (result == 0 && encoder_ready) {
            std::vector<EncodedFrame> frames;
            const auto timestamp = std::chrono::duration_cast<
                std::chrono::duration<std::uint64_t, std::ratio<1, 10'000'000>>>(
                    now - epoch).count();
            result = encoder_->encode(nv12, timestamp, frames);
            if (result < 0) {
                char message[96]{};
                std::snprintf(message, sizeof(message),
                              "H.264 frame submission failed (HRESULT 0x%08X).",
                              static_cast<unsigned int>(result));
                set_last_error(message);
            }
            if (result == S_FALSE) {
                std::lock_guard lock(stats_mutex_); ++stats_.frames_dropped;
                result = 0;
            }
            publish_frames(frames);
        }
        if (nv12) nv12->Release();
        if (result < 0) {
            std::lock_guard lock(stats_mutex_);
            ++stats_.frames_dropped;
        }
        const auto rate_now = std::chrono::steady_clock::now();
        const double rate_seconds = std::chrono::duration<double>(rate_now - rate_mark).count();
        if (rate_seconds >= 0.5) {
            std::lock_guard lock(stats_mutex_);
            stats_.capture_fps = static_cast<double>(rate_capture_frames) / rate_seconds;
            stats_.encode_fps = static_cast<double>(rate_encoded_frames) / rate_seconds;
            rate_capture_frames = 0;
            rate_encoded_frames = 0;
            rate_mark = rate_now;
        }
    }
}

EngineState SnowlinkEngine::get_state() const noexcept {
    return state_;
}

std::string SnowlinkEngine::last_error() const noexcept {
    std::lock_guard lock(error_mutex_);
    return last_error_;
}

void SnowlinkEngine::set_last_error(const char* message) noexcept {
    std::lock_guard lock(error_mutex_);
    last_error_ = message ? message : "";
}

} // namespace snowlink
