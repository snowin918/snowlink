#pragma once

#include "status_util.h"
#include "types.h"
#include <memory>

namespace snowlink {

class CaptureManager {
public:
    CaptureManager();
    ~CaptureManager();

    int32_t initialize();
    int32_t shutdown();
    int32_t start(const CaptureConfig& config);
    int32_t stop();
    int32_t set_capture_cursor_in_video(bool enabled);
    int32_t get_capture_status(CaptureStatus& out_status) const;
    int32_t get_stats(CaptureBackendStats& out_stats) const;

private:
    class State;
    std::unique_ptr<State> state_;
};

} // namespace snowlink
