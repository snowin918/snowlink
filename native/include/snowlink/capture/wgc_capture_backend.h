#pragma once

#include "snowlink/types.h"

#include <d3d11.h>
#include <cstdint>
#include <memory>

namespace snowlink {

// WGC producer whose output is always an ID3D11Texture2D. The returned texture
// is AddRef'd and belongs to the caller. No staging resource or CPU mapping is
// performed anywhere in this backend.
class WgcCaptureBackend final {
public:
    WgcCaptureBackend();
    ~WgcCaptureBackend();

    WgcCaptureBackend(const WgcCaptureBackend&) = delete;
    WgcCaptureBackend& operator=(const WgcCaptureBackend&) = delete;

    int32_t start(const CaptureConfig& config);
    int32_t stop();
    int32_t get_latest_frame(ID3D11Texture2D** texture, uint64_t* frame_id) const;
    int32_t set_capture_cursor_in_video(bool enabled);
    int32_t get_capture_status(CaptureStatus& status) const;
    int32_t get_stats(CaptureBackendStats& stats) const;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
    bool capture_cursor_in_video_ = false;
};

} // namespace snowlink
