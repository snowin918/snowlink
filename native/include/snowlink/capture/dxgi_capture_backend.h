#pragma once

#include "snowlink/capture/capture_backend.h"

#include <memory>

namespace snowlink {

class DxgiCaptureBackend final : public ICaptureBackend {
public:
    DxgiCaptureBackend();
    ~DxgiCaptureBackend();
    DxgiCaptureBackend(const DxgiCaptureBackend&) = delete;
    DxgiCaptureBackend& operator=(const DxgiCaptureBackend&) = delete;

    int32_t start(const CaptureConfig& config) override;
    int32_t stop() override;
    int32_t get_latest_frame(ID3D11Texture2D** texture, uint64_t* frame_id,
        FrameMetadata* metadata = nullptr, PointerState* pointer = nullptr) const override;
    int32_t set_capture_cursor_in_video(bool enabled) override;
    int32_t get_capture_status(CaptureStatus& status) const override;
    int32_t get_stats(CaptureBackendStats& stats) const override;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

} // namespace snowlink
