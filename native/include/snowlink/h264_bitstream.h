#pragma once

#include "encoder.h"

#include <cstdint>
#include <span>
#include <vector>

namespace snowlink {

struct H264AccessUnitInfo {
    bool has_idr = false;
    bool has_sps = false;
    bool has_pps = false;
};

// Inspect Annex-B H.264 without decoding it. Both three- and four-byte start
// codes are accepted because Media Foundation encoders may emit either form.
H264AccessUnitInfo inspect_h264_access_unit(std::span<const std::uint8_t> bytes);
bool normalize_h264_access_unit(std::vector<std::uint8_t>& bytes);
bool normalize_h264_sequence_header(std::vector<std::uint8_t>& bytes);

// A Media Foundation encoder exposes SPS/PPS through
// MF_MT_MPEG_SEQUENCE_HEADER and is not required to repeat them in each output
// sample. Make every random-access unit independently decodable before RTP
// packetization. The operation is idempotent.
void prepare_h264_access_unit(EncodedFrame& frame,
                              std::span<const std::uint8_t> sequence_header);

} // namespace snowlink
