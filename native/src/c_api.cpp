#include "snowlink/c_api.h"
#include "snowlink/engine.h"
#include "snowlink/transport.h"

#include <cstdint>
#include <cstring>
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

int32_t snowlink_engine_connect_transport(void* engine_handle, const SnowlinkTransportConfig* config) noexcept {
    if (!engine_handle || !config) return -1;
    TransportConfig internal{};
    if (config->bind_address) internal.bind_address = config->bind_address;
    internal.port_min = config->port_min ? config->port_min : 1024;
    internal.port_max = config->port_max ? config->port_max : 65535;
    internal.mtu = config->mtu ? config->mtu : 1200;
    internal.frame_queue_limit = config->frame_queue_limit ? config->frame_queue_limit : 2;
    internal.nack_packet_limit = config->nack_packet_limit ? config->nack_packet_limit : 256;
    return static_cast<SnowlinkEngine*>(engine_handle)->connect_transport(internal);
}

int32_t snowlink_engine_create_transport_offer(void* engine_handle) noexcept {
    return engine_handle ? static_cast<SnowlinkEngine*>(engine_handle)->create_transport_offer() : -1;
}

namespace {
int32_t copy_description_part(void* handle, char* buffer, uint32_t size, bool want_type) {
    if (!handle) return -1;
    std::string sdp, type;
    const int32_t result = static_cast<SnowlinkEngine*>(handle)->get_transport_local_description(sdp, type);
    if (result != 0) return result;
    const std::string& value = want_type ? type : sdp;
    const auto required = static_cast<uint32_t>(value.size() + 1);
    if (!buffer || size < required) return static_cast<int32_t>(required);
    std::memcpy(buffer, value.c_str(), required);
    return 0;
}
}

int32_t snowlink_engine_get_local_sdp(void* handle, char* buffer, uint32_t size) noexcept {
    return copy_description_part(handle, buffer, size, false);
}

int32_t snowlink_engine_get_local_sdp_type(void* handle, char* buffer, uint32_t size) noexcept {
    return copy_description_part(handle, buffer, size, true);
}

int32_t snowlink_engine_set_remote_sdp(void* handle, const char* sdp, const char* type) noexcept {
    if (!handle || !sdp || !type) return -1;
    return static_cast<SnowlinkEngine*>(handle)->set_transport_remote_description(sdp, type);
}

namespace { TransportConfig receive_config(const SnowlinkTransportConfig* c){TransportConfig x{};if(c->bind_address)x.bind_address=c->bind_address;x.port_min=c->port_min?c->port_min:1024;x.port_max=c->port_max?c->port_max:65535;x.mtu=c->mtu?c->mtu:1200;x.frame_queue_limit=2;x.nack_packet_limit=c->nack_packet_limit?c->nack_packet_limit:256;return x;} }
int32_t snowlink_engine_start_receiver(void* h,uint64_t hwnd,const SnowlinkTransportConfig* c)noexcept{return h&&c?static_cast<SnowlinkEngine*>(h)->start_receiver(hwnd,receive_config(c)):-1;}
int32_t snowlink_engine_create_receiver_answer(void* h)noexcept{return h?static_cast<SnowlinkEngine*>(h)->create_receiver_answer():-1;}
int32_t snowlink_engine_stop_receiver(void* h)noexcept{return h?static_cast<SnowlinkEngine*>(h)->stop_receiver():-1;}
int32_t snowlink_engine_receiver_resize(void* h)noexcept{return h?static_cast<SnowlinkEngine*>(h)->receiver_resize():-1;}
int32_t snowlink_engine_receiver_set_visible(void* h,int32_t v)noexcept{return h?static_cast<SnowlinkEngine*>(h)->receiver_set_visible(v!=0):-1;}
int32_t snowlink_engine_send_input(void*h,const SnowlinkInputEvent*e)noexcept{if(!h||!e)return-1;RemoteInputEvent x;x.kind=static_cast<InputKind>(e->kind);x.code=e->code;x.down=e->down!=0;x.x=e->x;x.y=e->y;x.delta=e->delta;x.sequence=e->sequence;return static_cast<SnowlinkEngine*>(h)->send_remote_input(x);}
int32_t snowlink_engine_set_remote_input_enabled(void* h, int32_t enabled) noexcept {
    return h ? static_cast<SnowlinkEngine*>(h)->set_remote_input_enabled(enabled != 0) : -1;
}
int32_t snowlink_engine_get_decoder_name(void* h,char* buffer,uint32_t size)noexcept{if(!h)return-1;std::string name;bool hw;uint32_t w,hh;double fps;auto r=static_cast<SnowlinkEngine*>(h)->get_decoder_info(name,hw,w,hh,fps);if(r)return r;uint32_t need=static_cast<uint32_t>(name.size()+1);if(!buffer||size<need)return static_cast<int32_t>(need);memcpy(buffer,name.c_str(),need);return 0;}
int32_t snowlink_engine_get_decoder_status(void* h,int32_t* hw,uint32_t* w,uint32_t* height,double* fps)noexcept{if(!h||!hw||!w||!height||!fps)return-1;std::string name;bool hardware;auto r=static_cast<SnowlinkEngine*>(h)->get_decoder_info(name,hardware,*w,*height,*fps);*hw=hardware?1:0;return r;}

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
    stats->decode_fps = internal.decode_fps;
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
    stats->send_bitrate = internal.send_bitrate;
    stats->packets_sent = internal.packets_sent;
    stats->packets_dropped = internal.packets_dropped;
    stats->transport_frames_dropped = internal.transport_frames_dropped;
    stats->transport_errors = internal.transport_errors;
    stats->transport_queue_depth = internal.transport_queue_depth;
    stats->estimated_loss = internal.estimated_loss;
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
