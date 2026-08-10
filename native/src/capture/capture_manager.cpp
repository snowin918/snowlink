#include "snowlink/capture.h"

namespace snowlink {

CaptureManager::CaptureManager() = default;
CaptureManager::~CaptureManager() = default;

int32_t CaptureManager::initialize() {
    return 0;
}

int32_t CaptureManager::shutdown() {
    return 0;
}

int32_t CaptureManager::start(const CaptureConfig& config) {
    return 0;
}

int32_t CaptureManager::stop() {
    return 0;
}

} // namespace snowlink
