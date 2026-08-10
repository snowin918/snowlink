#pragma once

#include "status_util.h"

namespace snowlink {

class Decoder {
public:
    Decoder();
    ~Decoder();

    int32_t initialize();
    int32_t shutdown();
};

} // namespace snowlink
