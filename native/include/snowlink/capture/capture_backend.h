#pragma once

#include "snowlink/types.h"

#include <d3d11.h>
#include <memory>

namespace snowlink {

class ICaptureBackend {
public:
    virtual ~ICaptureBackend() = default;
    virtual int32_t start(const CaptureConfig& config) = 0;
    virtual int32_t stop() = 0;
    virtual int32_t get_latest_frame(ID3D11Texture2D** texture, uint64_t* frame_id,
                                     FrameMetadata* metadata = nullptr,
                                     PointerState* pointer = nullptr) const = 0;
    virtual int32_t set_capture_cursor_in_video(bool enabled) = 0;
    virtual int32_t get_capture_status(CaptureStatus& status) const = 0;
    virtual int32_t get_stats(CaptureBackendStats& stats) const = 0;
};

} // namespace snowlink
