#pragma once

#include "status_util.h"

namespace snowlink {

class Transport {
public:
    Transport();
    ~Transport();

    int32_t initialize();
    int32_t shutdown();
};

} // namespace snowlink
