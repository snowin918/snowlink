#include "snowlink/encoder.h"

namespace snowlink {

Encoder::Encoder() = default;
Encoder::~Encoder() = default;

int32_t Encoder::initialize() {
    return 0;
}

int32_t Encoder::shutdown() {
    return 0;
}

int32_t Encoder::set_bitrate(std::int32_t bitrate_bps) {
    return 0;
}

int32_t Encoder::set_resolution(std::int32_t width, std::int32_t height) {
    return 0;
}

int32_t Encoder::request_keyframe() {
    return 0;
}

} // namespace snowlink
