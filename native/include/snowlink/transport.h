#pragma once

#include "encoder.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace snowlink {

struct TransportConfig {
    std::string bind_address;
    std::uint16_t port_min = 1024;
    std::uint16_t port_max = 65535;
    std::size_t mtu = 1200;
    std::size_t frame_queue_limit = 2;
    std::size_t nack_packet_limit = 256;
};

struct TransportStats {
    std::uint64_t bytes_sent = 0;
    std::uint64_t packets_sent = 0;
    std::uint64_t packets_dropped = 0;
    std::uint64_t frames_dropped = 0;
    std::uint64_t transport_errors = 0;
    std::uint32_t queue_depth = 0;
    double send_bitrate = 0.0;
    double rtt = 0.0;
    double estimated_loss = 0.0;
    bool connected = false;
};

// Native WebRTC media sender. Signaling remains deliberately external: Python
// transports the SDP strings only after Snowlink's pairing/approval succeeds.
class Transport {
public:
    using KeyframeRequest = void (*)(void* context);
    using AccessUnitCallback = void (*)(void* context, const std::uint8_t* data,
                                        std::size_t size, std::uint64_t timestamp);
    using ControlCallback = void (*)(void* context, const std::uint8_t* data,
                                     std::size_t size);

    Transport();
    ~Transport();
    Transport(const Transport&) = delete;
    Transport& operator=(const Transport&) = delete;

    int32_t initialize(const TransportConfig& config, KeyframeRequest on_keyframe,
                       void* keyframe_context, ControlCallback on_input=nullptr,
                       void* control_context=nullptr);
    int32_t initialize_receiver(const TransportConfig& config, AccessUnitCallback callback,
                                void* callback_context, ControlCallback on_cursor=nullptr,
                                void* control_context=nullptr);
    int32_t create_offer();
    int32_t create_answer();
    int32_t get_local_description(std::string& sdp, std::string& type) const;
    int32_t set_remote_description(const std::string& sdp, const std::string& type);
    int32_t enqueue(EncodedFrame frame);
    int32_t send_cursor(std::vector<std::uint8_t> message, bool shape);
    int32_t send_input(std::vector<std::uint8_t> message);
    int32_t request_remote_keyframe();
    int32_t get_stats(TransportStats& stats) const;
    int32_t shutdown();

private:
    class State;
    std::unique_ptr<State> state_;
};

} // namespace snowlink
