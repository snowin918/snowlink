#include "snowlink/transport.h"

namespace snowlink {

Transport::Transport() = default;
Transport::~Transport() = default;

int32_t Transport::initialize() {
    return 0;
}

int32_t Transport::shutdown() {
    return 0;
}

} // namespace snowlink
