#pragma once

#include "status_util.h"

namespace snowlink {

class InputSubsystem {
public:
    InputSubsystem();
    ~InputSubsystem();

    int32_t initialize();
    int32_t shutdown();
};

} // namespace snowlink
