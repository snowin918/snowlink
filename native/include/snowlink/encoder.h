#pragma once

#include "status_util.h"
#include "types.h"

namespace snowlink {

class Encoder {
public:
    Encoder();
    ~Encoder();

    int32_t initialize();
    int32_t shutdown();
    int32_t set_bitrate(std::int32_t bitrate_bps);
    int32_t set_resolution(std::int32_t width, std::int32_t height);
    int32_t request_keyframe();
};

} // namespace snowlink
