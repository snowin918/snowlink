#pragma once

#include "status_util.h"
#include "types.h"

namespace snowlink {

class CaptureManager {
public:
    CaptureManager();
    ~CaptureManager();

    int32_t initialize();
    int32_t shutdown();
    int32_t start(const CaptureConfig& config);
    int32_t stop();
};

} // namespace snowlink
