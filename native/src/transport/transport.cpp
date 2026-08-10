#include "snowlink/transport.h"

#include <rtc/rtc.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <random>
#include <thread>

namespace snowlink {
namespace {
constexpr std::uint8_t kH264PayloadType = 102;
std::uint32_t random_u32() {
    std::random_device rd;
    return (static_cast<std::uint32_t>(rd()) << 16) ^ static_cast<std::uint32_t>(rd());
}
}

class Transport::State {
public:
    mutable std::mutex mutex;
    std::condition_variable wake;
    TransportConfig config;
    std::shared_ptr<rtc::PeerConnection> peer;
    std::shared_ptr<rtc::Track> track;
    std::shared_ptr<rtc::DataChannel> video_data, cursor_motion, cursor_shape, input;
    std::shared_ptr<rtc::RtpPacketizationConfig> rtp;
    std::deque<EncodedFrame> queue;
    std::thread sender;
    bool stopping = false;
    bool local_ready = false;
    bool gathering_complete = false;
    std::string local_sdp;
    std::string local_type;
    TransportStats stats;
    std::uint64_t last_bytes = 0;
    std::chrono::steady_clock::time_point bitrate_mark{};
    KeyframeRequest keyframe_callback = nullptr;
    void* keyframe_context = nullptr;
    AccessUnitCallback access_unit_callback = nullptr;
    void* access_unit_context = nullptr;
    ControlCallback input_callback=nullptr,cursor_callback=nullptr;
    void* control_context=nullptr;

    void run() {
        for (;;) {
            EncodedFrame frame;
            std::shared_ptr<rtc::DataChannel> output;
            {
                std::unique_lock lock(mutex);
                wake.wait(lock, [&] { return stopping || (!queue.empty() && video_data && video_data->isOpen()); });
                if (stopping) return;
                frame = std::move(queue.front());
                queue.pop_front();
                stats.queue_depth = static_cast<std::uint32_t>(queue.size());
                output = video_data;
            }
            try {
                // Media Foundation timestamps and WebRTC both have arbitrary epochs.
                // Preserve the native 100 ns timestamp and convert only its rate.
                output->send(reinterpret_cast<const rtc::byte*>(frame.bytes.data()), frame.bytes.size());
                std::lock_guard lock(mutex);
                stats.bytes_sent += frame.bytes.size();
                ++stats.packets_sent;
                update_rate_locked();
            } catch (...) {
                std::lock_guard lock(mutex);
                ++stats.packets_dropped;
                ++stats.transport_errors;
            }
        }
    }

    void update_rate_locked() {
        const auto now = std::chrono::steady_clock::now();
        if (bitrate_mark.time_since_epoch().count() == 0) bitrate_mark = now;
        const double elapsed = std::chrono::duration<double>(now - bitrate_mark).count();
        if (elapsed >= 0.5) {
            stats.send_bitrate = static_cast<double>(stats.bytes_sent - last_bytes) * 8.0 / elapsed;
            last_bytes = stats.bytes_sent;
            bitrate_mark = now;
        }
    }
};

Transport::Transport() : state_(std::make_unique<State>()) {}
Transport::~Transport() { shutdown(); }

namespace {
rtc::Configuration receiver_configuration(const TransportConfig& config) {
    rtc::Configuration c;
    if (!config.bind_address.empty()) c.bindAddress = config.bind_address;
    c.portRangeBegin=config.port_min; c.portRangeEnd=config.port_max; c.mtu=config.mtu;
    c.forceMediaTransport=true; c.disableAutoNegotiation=true; return c;
}
}

int32_t Transport::initialize_receiver(const TransportConfig& config, AccessUnitCallback callback,
                                       void* context, ControlCallback cursor_callback, void* control_context) {
    shutdown();
    if (!callback || config.port_min > config.port_max) return -1;
    try {
        auto peer=std::make_shared<rtc::PeerConnection>(receiver_configuration(config));
        auto video=rtc::Description::Video("video",rtc::Description::Direction::RecvOnly);
        video.addH264Codec(kH264PayloadType,"profile-level-id=4d001f;packetization-mode=1;level-asymmetry-allowed=1");
        auto track=peer->addTrack(video);
        peer->onDataChannel([this](std::shared_ptr<rtc::DataChannel> channel){
            const auto label=channel->label();
            if(label=="snowlink.video"){
                channel->onMessage([this](rtc::message_variant message){if(auto data=std::get_if<rtc::binary>(&message)){AccessUnitCallback cb=nullptr;void*ctx=nullptr;{std::lock_guard lock(state_->mutex);cb=state_->access_unit_callback;ctx=state_->access_unit_context;}if(cb&&!data->empty())cb(ctx,reinterpret_cast<const uint8_t*>(data->data()),data->size(),static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count()/100));}});
                std::lock_guard lock(state_->mutex);state_->video_data=channel;
            } else if(label=="snowlink.cursor.motion"||label=="snowlink.cursor.shape"){
                channel->onMessage([this](rtc::message_variant message){if(auto data=std::get_if<rtc::binary>(&message)){ControlCallback cb=nullptr;void*ctx=nullptr;{std::lock_guard lock(state_->mutex);cb=state_->cursor_callback;ctx=state_->control_context;}if(cb&&!data->empty())cb(ctx,reinterpret_cast<const uint8_t*>(data->data()),data->size());}});
                std::lock_guard lock(state_->mutex);if(label=="snowlink.cursor.motion")state_->cursor_motion=channel;else state_->cursor_shape=channel;
            } else if(label=="snowlink.input") { std::lock_guard lock(state_->mutex);state_->input=channel; }
        });
        // Incoming traversal is tail-to-root: classify RTP/RTCP first, then
        // reconstruct H.264 access units. RTCP must not leak into the video
        // callback as a binary access unit.
        auto depacketizer=std::make_shared<rtc::H264RtpDepacketizer>(
            rtc::NalUnit::Separator::StartSequence);
        depacketizer->addToChain(std::make_shared<rtc::RtcpReceivingSession>());
        track->setMediaHandler(depacketizer);
        track->onMessage([this](rtc::binary data) {
            AccessUnitCallback cb=nullptr; void* ctx=nullptr;
            { std::lock_guard lock(state_->mutex); cb=state_->access_unit_callback; ctx=state_->access_unit_context; }
            if (cb && !data.empty()) cb(ctx,reinterpret_cast<const std::uint8_t*>(data.data()),data.size(),
                static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::steady_clock::now().time_since_epoch()).count()/100));
        }, nullptr);
        // Snowlink signaling is deliberately non-trickle.  onLocalDescription
        // fires before libdatachannel has appended gathered host candidates, so
        // publishing the SDP here produces an offer/answer which can never form
        // an ICE pair.  Wait for GatheringState::Complete and then read the
        // peer's current description, which includes every gathered candidate.
        peer->onLocalDescription([this](rtc::Description d){
            std::lock_guard lock(state_->mutex);
            state_->local_type=d.typeString();
        });
        peer->onGatheringStateChange([this](rtc::PeerConnection::GatheringState s){
            if(s!=rtc::PeerConnection::GatheringState::Complete)return;
            std::lock_guard lock(state_->mutex);
            state_->gathering_complete=true;
        });
        peer->onStateChange([this](rtc::PeerConnection::State s){std::lock_guard lock(state_->mutex);state_->stats.connected=s==rtc::PeerConnection::State::Connected;if(s==rtc::PeerConnection::State::Failed)++state_->stats.transport_errors;});
        std::lock_guard lock(state_->mutex); state_->config=config;state_->peer=std::move(peer);state_->track=std::move(track);
        state_->access_unit_callback=callback;state_->access_unit_context=context;state_->cursor_callback=cursor_callback;state_->control_context=control_context;state_->stopping=false; return 0;
    } catch (...) { shutdown(); return -2; }
}

int32_t Transport::initialize(const TransportConfig& config, KeyframeRequest callback,
                              void* context, ControlCallback input_callback, void* control_context) {
    shutdown();
    if (config.mtu < 576 || config.mtu > 1500 || config.frame_queue_limit == 0 ||
        config.port_min > config.port_max) return -1;
    try {
        rtc::Configuration rtc_config;
        if (!config.bind_address.empty()) rtc_config.bindAddress = config.bind_address;
        rtc_config.portRangeBegin = config.port_min;
        rtc_config.portRangeEnd = config.port_max;
        rtc_config.mtu = config.mtu;
        rtc_config.forceMediaTransport = true;
        rtc_config.disableAutoNegotiation = true;

        auto peer = std::make_shared<rtc::PeerConnection>(rtc_config);
        auto video = rtc::Description::Video("video", rtc::Description::Direction::SendOnly);
        video.addH264Codec(kH264PayloadType,
            "profile-level-id=4d001f;packetization-mode=1;level-asymmetry-allowed=1");
        const auto ssrc = random_u32();
        video.addSSRC(ssrc, "snowlink-video", "snowlink-stream", "snowlink-video");
        auto track = peer->addTrack(video);
        rtc::DataChannelInit video_init;video_init.reliability.unordered=true;video_init.reliability.maxRetransmits=0;
        auto video_data=peer->createDataChannel("snowlink.video",video_init);
        rtc::DataChannelInit motion_init;motion_init.reliability.unordered=true;motion_init.reliability.maxRetransmits=0;
        auto cursor_motion=peer->createDataChannel("snowlink.cursor.motion",motion_init);
        auto cursor_shape=peer->createDataChannel("snowlink.cursor.shape");
        auto input=peer->createDataChannel("snowlink.input");
        input->onMessage([this](rtc::message_variant message){if(auto data=std::get_if<rtc::binary>(&message)){ControlCallback cb=nullptr;void*ctx=nullptr;{std::lock_guard lock(state_->mutex);cb=state_->input_callback;ctx=state_->control_context;}if(cb&&!data->empty())cb(ctx,reinterpret_cast<const uint8_t*>(data->data()),data->size());}});
        auto rtp = std::make_shared<rtc::RtpPacketizationConfig>(
            ssrc, "snowlink-video", kH264PayloadType, rtc::H264RtpPacketizer::ClockRate);
        auto packetizer = std::make_shared<rtc::H264RtpPacketizer>(
            rtc::NalUnit::Separator::StartSequence, rtp,
            config.mtu > 100 ? config.mtu - 100 : config.mtu);
        packetizer->addToChain(std::make_shared<rtc::RtcpSrReporter>(rtp));
        packetizer->addToChain(std::make_shared<rtc::RtcpNackResponder>(config.nack_packet_limit));
        packetizer->addToChain(std::make_shared<rtc::PliHandler>([this] {
            KeyframeRequest cb = nullptr;
            void* cb_context = nullptr;
            {
                std::lock_guard lock(state_->mutex);
                cb = state_->keyframe_callback;
                cb_context = state_->keyframe_context;
            }
            if (cb) cb(cb_context);
        }));
        track->setMediaHandler(packetizer);
        track->onOpen([this] { state_->wake.notify_all(); });
        video_data->onOpen([this] { state_->wake.notify_all(); });
        peer->onLocalDescription([this](rtc::Description description) {
            std::lock_guard lock(state_->mutex);
            state_->local_type = description.typeString();
        });
        peer->onGatheringStateChange([this](rtc::PeerConnection::GatheringState gathering_state) {
            if (gathering_state != rtc::PeerConnection::GatheringState::Complete) return;
            std::lock_guard lock(state_->mutex);
            state_->gathering_complete = true;
        });
        peer->onStateChange([this](rtc::PeerConnection::State connection_state) {
            std::lock_guard lock(state_->mutex);
            state_->stats.connected = connection_state == rtc::PeerConnection::State::Connected;
            if (connection_state == rtc::PeerConnection::State::Failed) ++state_->stats.transport_errors;
        });
        {
            std::lock_guard lock(state_->mutex);
            state_->config = config;
            state_->peer = std::move(peer);
            state_->track = std::move(track);
            state_->rtp = std::move(rtp);
            state_->video_data=std::move(video_data);state_->cursor_motion=std::move(cursor_motion);state_->cursor_shape=std::move(cursor_shape);state_->input=std::move(input);
            state_->keyframe_callback = callback;
            state_->keyframe_context = context;
            state_->input_callback=input_callback;state_->control_context=control_context;
            state_->stopping = false;
        }
        state_->sender = std::thread([this] { state_->run(); });
        return 0;
    } catch (...) {
        shutdown();
        return -2;
    }
}

int32_t Transport::send_cursor(std::vector<uint8_t> message,bool shape){std::shared_ptr<rtc::DataChannel> c;{std::lock_guard lock(state_->mutex);c=shape?state_->cursor_shape:state_->cursor_motion;}if(!c||!c->isOpen())return 1;if(!shape&&c->bufferedAmount()>message.size())return 1;try{c->send(reinterpret_cast<const rtc::byte*>(message.data()),message.size());return 0;}catch(...){return -2;}}
int32_t Transport::send_input(std::vector<uint8_t> message){std::shared_ptr<rtc::DataChannel> c;{std::lock_guard lock(state_->mutex);c=state_->input;}if(!c||!c->isOpen())return 1;const bool move=message.size()>2&&message[0]==1&&message[1]==3&&message[2]==1;if(move&&c->bufferedAmount()>message.size())return 1;try{c->send(reinterpret_cast<const rtc::byte*>(message.data()),message.size());return 0;}catch(...){return -2;}}

int32_t Transport::create_offer() {
    std::shared_ptr<rtc::PeerConnection> peer;
    { std::lock_guard lock(state_->mutex); peer = state_->peer; state_->local_ready = false; state_->gathering_complete = false; }
    if (!peer) return -1;
    try { peer->setLocalDescription(rtc::Description::Type::Offer); return 0; }
    catch (...) { return -2; }
}

int32_t Transport::create_answer() {
    std::shared_ptr<rtc::PeerConnection> peer;
    { std::lock_guard lock(state_->mutex); peer=state_->peer; state_->local_ready=false; state_->gathering_complete=false; }
    if(!peer)return -1; try{peer->setLocalDescription(rtc::Description::Type::Answer);return 0;}catch(...){return -2;}
}

int32_t Transport::request_remote_keyframe() {
    std::shared_ptr<rtc::Track> track; {std::lock_guard lock(state_->mutex);track=state_->track;}
    return track && track->requestKeyframe() ? 0 : -1;
}

int32_t Transport::get_local_description(std::string& sdp, std::string& type) const {
    std::shared_ptr<rtc::PeerConnection> peer;
    {
        std::lock_guard lock(state_->mutex);
        if (!state_->gathering_complete) return 1;
        if (state_->local_ready) {
            sdp = state_->local_sdp;
            type = state_->local_type;
            return 0;
        }
        peer = state_->peer;
    }
    if (!peer) return -1;
    try {
        const auto description = peer->localDescription();
        if (!description) return 1;
        sdp = static_cast<std::string>(*description);
        type = description->typeString();
        std::lock_guard lock(state_->mutex);
        state_->local_sdp = sdp;
        state_->local_type = type;
        state_->local_ready = true;
        return 0;
    } catch (...) {
        return -2;
    }
}

int32_t Transport::set_remote_description(const std::string& sdp, const std::string& type) {
    std::shared_ptr<rtc::PeerConnection> peer;
    { std::lock_guard lock(state_->mutex); peer = state_->peer; }
    if (!peer || sdp.empty()) return -1;
    try { peer->setRemoteDescription(rtc::Description(sdp, type)); return 0; }
    catch (...) { return -2; }
}

int32_t Transport::enqueue(EncodedFrame frame) {
    if (frame.bytes.empty()) return -1;
    std::lock_guard lock(state_->mutex);
    if (!state_->peer || state_->stopping) return -2;
    while (state_->queue.size() >= state_->config.frame_queue_limit) {
        state_->queue.pop_front();
        ++state_->stats.frames_dropped;
    }
    state_->queue.push_back(std::move(frame));
    state_->stats.queue_depth = static_cast<std::uint32_t>(state_->queue.size());
    state_->wake.notify_one();
    return 0;
}

int32_t Transport::get_stats(TransportStats& stats) const {
    // Do not call into libdatachannel while holding the Snowlink state lock.
    // libdatachannel may concurrently invoke one of our callbacks while holding
    // its own internal lock; taking the locks in the opposite order here can
    // deadlock the stats thread and, subsequently, Qt input dispatch.
    std::shared_ptr<rtc::PeerConnection> peer;
    {
        std::lock_guard lock(state_->mutex);
        stats = state_->stats;
        peer = state_->peer;
    }
    if (peer) {
        if (auto rtt = peer->rtt()) stats.rtt = static_cast<double>(rtt->count());
    }
    return 0;
}

int32_t Transport::shutdown() {
    std::shared_ptr<rtc::PeerConnection> peer;
    {
        std::lock_guard lock(state_->mutex);
        state_->stopping = true;
        state_->queue.clear();
        state_->stats.queue_depth = 0;
        peer = state_->peer;
    }
    state_->wake.notify_all();
    if (state_->sender.joinable()) state_->sender.join();
    if (peer) peer->close();
    std::lock_guard lock(state_->mutex);
    state_->track.reset(); state_->rtp.reset();state_->video_data.reset();state_->cursor_motion.reset();state_->cursor_shape.reset();state_->input.reset(); state_->peer.reset();
    state_->access_unit_callback=nullptr; state_->access_unit_context=nullptr;
    state_->local_ready = false; state_->gathering_complete = false; state_->stats.connected = false;
    return 0;
}

} // namespace snowlink
