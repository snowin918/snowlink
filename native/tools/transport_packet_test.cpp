#include <rtc/rtc.hpp>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <memory>
#include <vector>

namespace {
rtc::binary make_frame() {
    rtc::binary frame{rtc::byte{0}, rtc::byte{0}, rtc::byte{0}, rtc::byte{1}, rtc::byte{0x65}};
    for (std::uint32_t i = 0; i < 8192; ++i) frame.push_back(rtc::byte(i % 251));
    return frame;
}

rtc::message_vector packetize(const rtc::binary& frame) {
    auto config = std::make_shared<rtc::RtpPacketizationConfig>(
        0x10203040u, "test", static_cast<std::uint8_t>(102),
        rtc::H264RtpPacketizer::ClockRate);
    auto packetizer = std::make_shared<rtc::H264RtpPacketizer>(
        rtc::NalUnit::Separator::StartSequence, config, 1100);
    auto message = rtc::make_message(frame.begin(), frame.end(),
                                     std::make_shared<rtc::FrameInfo>(9000));
    rtc::message_vector messages{std::move(message)};
    packetizer->outgoingChain(messages, nullptr);
    return messages;
}

rtc::binary depacketize(rtc::message_vector messages) {
    auto depacketizer = std::make_shared<rtc::H264RtpDepacketizer>(
        rtc::NalUnit::Separator::StartSequence);
    depacketizer->incomingChain(messages, nullptr);
    if (messages.size() != 1) return {};
    return rtc::binary(messages.front()->begin(), messages.front()->end());
}

rtc::binary receive_chain(rtc::message_vector messages) {
    // MediaHandler incoming traversal is tail-to-root. This mirrors the real
    // receiver and prevents regressions where a reconstructed H.264 access unit
    // is incorrectly passed into RtcpReceivingSession and discarded as bad RTP.
    auto depacketizer = std::make_shared<rtc::H264RtpDepacketizer>(
        rtc::NalUnit::Separator::StartSequence);
    depacketizer->addToChain(std::make_shared<rtc::RtcpReceivingSession>());
    depacketizer->incomingChain(messages, nullptr);
    if (messages.size() != 1) return {};
    return rtc::binary(messages.front()->begin(), messages.front()->end());
}
}

int main() {
    const auto frame = make_frame();
    auto packets = packetize(frame);
    if (packets.size() < 2) { std::cerr << "fragmentation did not occur\n"; return 1; }
    if (std::any_of(packets.begin(), packets.end(), [](const auto& p) { return p->size() > 1200; })) {
        std::cerr << "packet exceeded path MTU\n"; return 2;
    }
    if (depacketize(packets) != frame) { std::cerr << "ordered reconstruction failed\n"; return 3; }
    if (receive_chain(packets) != frame) {
        std::cerr << "RTCP plus H.264 receive chain discarded the access unit\n";
        return 6;
    }

    auto reordered = packets;
    std::reverse(reordered.begin(), reordered.end() - 1); // marker remains the flush boundary
    if (depacketize(std::move(reordered)) != frame) {
        std::cerr << "reordered reconstruction failed\n"; return 4;
    }

    auto lossy = packets;
    lossy.erase(lossy.begin() + static_cast<std::ptrdiff_t>(lossy.size() / 2));
    if (depacketize(std::move(lossy)) == frame) {
        std::cerr << "lossy frame was incorrectly accepted as complete\n"; return 5;
    }
    std::cout << "transport packet tests passed: fragments=" << packets.size()
              << " mtu<=1200 reconstruction=ok reorder=ok loss=discarded\n";
    return 0;
}
