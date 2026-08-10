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
    std::shared_ptr<rtc::RtpPacketizationConfig> rtp;
    std::deque<EncodedFrame> queue;
    std::thread sender;
    bool stopping = false;
    bool local_ready = false;
    std::string local_sdp;
    std::string local_type;
    TransportStats stats;
    std::uint64_t last_bytes = 0;
    std::chrono::steady_clock::time_point bitrate_mark{};
    KeyframeRequest keyframe_callback = nullptr;
    void* keyframe_context = nullptr;

    void run() {
        for (;;) {
            EncodedFrame frame;
            std::shared_ptr<rtc::Track> output;
            {
                std::unique_lock lock(mutex);
                wake.wait(lock, [&] { return stopping || (!queue.empty() && track && track->isOpen()); });
                if (stopping) return;
                frame = std::move(queue.front());
                queue.pop_front();
                stats.queue_depth = static_cast<std::uint32_t>(queue.size());
                output = track;
            }
            try {
                // Media Foundation timestamps and WebRTC both have arbitrary epochs.
                // Preserve the native 100 ns timestamp and convert only its rate.
                rtc::FrameInfo info(std::chrono::duration<double>(frame.timestamp / 10'000'000.0));
                const std::uint16_t sequence_before = rtp ? rtp->sequenceNumber : 0;
                output->sendFrame(reinterpret_cast<const rtc::byte*>(frame.bytes.data()),
                                  frame.bytes.size(), info);
                std::lock_guard lock(mutex);
                stats.bytes_sent += frame.bytes.size();
                if (rtp) stats.packets_sent += static_cast<std::uint16_t>(
                    rtp->sequenceNumber - sequence_before);
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

int32_t Transport::initialize(const TransportConfig& config, KeyframeRequest callback,
                              void* context) {
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
        peer->onLocalDescription([this](rtc::Description description) {
            std::lock_guard lock(state_->mutex);
            state_->local_sdp = static_cast<std::string>(description);
            state_->local_type = description.typeString();
            state_->local_ready = true;
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
            state_->keyframe_callback = callback;
            state_->keyframe_context = context;
            state_->stopping = false;
        }
        state_->sender = std::thread([this] { state_->run(); });
        return 0;
    } catch (...) {
        shutdown();
        return -2;
    }
}

int32_t Transport::create_offer() {
    std::shared_ptr<rtc::PeerConnection> peer;
    { std::lock_guard lock(state_->mutex); peer = state_->peer; state_->local_ready = false; }
    if (!peer) return -1;
    try { peer->setLocalDescription(rtc::Description::Type::Offer); return 0; }
    catch (...) { return -2; }
}

int32_t Transport::get_local_description(std::string& sdp, std::string& type) const {
    std::lock_guard lock(state_->mutex);
    if (!state_->local_ready) return 1;
    sdp = state_->local_sdp; type = state_->local_type; return 0;
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
    std::lock_guard lock(state_->mutex);
    stats = state_->stats;
    if (state_->peer) {
        if (auto rtt = state_->peer->rtt()) stats.rtt = static_cast<double>(rtt->count());
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
    state_->track.reset(); state_->rtp.reset(); state_->peer.reset();
    state_->local_ready = false; state_->stats.connected = false;
    return 0;
}

} // namespace snowlink
