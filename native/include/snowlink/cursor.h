#pragma once

#include "status_util.h"

namespace snowlink {

class CursorSubsystem {
public:
    CursorSubsystem();
    ~CursorSubsystem();

    int32_t initialize();
    int32_t shutdown();
};

} // namespace snowlink
