#include "snowlink/h264_bitstream.h"

#include <algorithm>
#include <vector>

namespace snowlink {
namespace {

std::size_t start_code_size(std::span<const std::uint8_t> bytes, std::size_t offset) {
    if (offset + 4 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 &&
        bytes[offset + 2] == 0 && bytes[offset + 3] == 1) {
        return 4;
    }
    if (offset + 3 <= bytes.size() && bytes[offset] == 0 && bytes[offset + 1] == 0 &&
        bytes[offset + 2] == 1) {
        return 3;
    }
    return 0;
}

void append_start_coded(std::vector<std::uint8_t>& output, const std::uint8_t* data,
                        std::size_t size) {
    static constexpr std::uint8_t start[]{0, 0, 0, 1};
    output.insert(output.end(), std::begin(start), std::end(start));
    output.insert(output.end(), data, data + size);
}

} // namespace

H264AccessUnitInfo inspect_h264_access_unit(std::span<const std::uint8_t> bytes) {
    H264AccessUnitInfo result{};
    for (std::size_t offset = 0; offset < bytes.size();) {
        const std::size_t prefix = start_code_size(bytes, offset);
        if (prefix == 0) {
            ++offset;
            continue;
        }
        const std::size_t header = offset + prefix;
        if (header >= bytes.size()) break;
        switch (bytes[header] & 0x1f) {
        case 5:
            result.has_idr = true;
            break;
        case 7:
            result.has_sps = true;
            break;
        case 8:
            result.has_pps = true;
            break;
        default:
            break;
        }
        offset = header + 1;
    }
    return result;
}

bool normalize_h264_access_unit(std::vector<std::uint8_t>& bytes) {
    if (bytes.empty()) return false;
    for (std::size_t offset = 0; offset < std::min<std::size_t>(bytes.size(), 4); ++offset)
        if (start_code_size(bytes, offset) != 0) return true;
    std::vector<std::uint8_t> annex_b;
    std::size_t offset = 0;
    while (offset + 4 <= bytes.size()) {
        const std::uint32_t size = (static_cast<std::uint32_t>(bytes[offset]) << 24) |
            (static_cast<std::uint32_t>(bytes[offset + 1]) << 16) |
            (static_cast<std::uint32_t>(bytes[offset + 2]) << 8) | bytes[offset + 3];
        offset += 4;
        if (size == 0 || size > bytes.size() - offset) return false;
        append_start_coded(annex_b, bytes.data() + offset, size);
        offset += size;
    }
    if (offset != bytes.size() || annex_b.empty()) return false;
    bytes.swap(annex_b);
    return true;
}

bool normalize_h264_sequence_header(std::vector<std::uint8_t>& bytes) {
    if (bytes.empty()) return false;
    if (inspect_h264_access_unit(bytes).has_sps) return true;
    if (bytes.size() < 7 || bytes[0] != 1) return false;
    std::size_t offset = 5;
    const std::uint8_t sps_count = bytes[offset++] & 0x1f;
    std::vector<std::uint8_t> annex_b;
    auto copy_units = [&bytes, &offset, &annex_b](std::uint8_t count) {
        for (std::uint8_t index = 0; index < count; ++index) {
            if (offset + 2 > bytes.size()) return false;
            const std::uint16_t size = static_cast<std::uint16_t>(
                (static_cast<std::uint16_t>(bytes[offset]) << 8) | bytes[offset + 1]);
            offset += 2;
            if (size == 0 || size > bytes.size() - offset) return false;
            append_start_coded(annex_b, bytes.data() + offset, size);
            offset += size;
        }
        return true;
    };
    if (!copy_units(sps_count) || offset >= bytes.size()) return false;
    const std::uint8_t pps_count = bytes[offset++];
    if (!copy_units(pps_count)) return false;
    const auto info = inspect_h264_access_unit(annex_b);
    if (!info.has_sps || !info.has_pps) return false;
    bytes.swap(annex_b);
    return true;
}

void prepare_h264_access_unit(EncodedFrame& frame,
                              std::span<const std::uint8_t> sequence_header) {
    (void)normalize_h264_access_unit(frame.bytes);
    const auto frame_info = inspect_h264_access_unit(frame.bytes);
    frame.keyframe = frame.keyframe || frame_info.has_idr;
    if (!frame.keyframe || (frame_info.has_sps && frame_info.has_pps)) return;

    const auto header_info = inspect_h264_access_unit(sequence_header);
    if (!header_info.has_sps || !header_info.has_pps) return;

    std::vector<std::uint8_t> complete;
    complete.reserve(sequence_header.size() + frame.bytes.size());
    complete.insert(complete.end(), sequence_header.begin(), sequence_header.end());
    complete.insert(complete.end(), frame.bytes.begin(), frame.bytes.end());
    frame.bytes.swap(complete);
}

} // namespace snowlink
