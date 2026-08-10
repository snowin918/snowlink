#pragma once

#include "status_util.h"

namespace snowlink {

class Renderer {
public:
    Renderer();
    ~Renderer();

    int32_t initialize();
    int32_t shutdown();
};

} // namespace snowlink
