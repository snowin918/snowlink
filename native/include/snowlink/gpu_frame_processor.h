#pragma once

#include "types.h"

#include <d3d11.h>
#include <memory>

namespace snowlink {

enum class GpuPixelFormat : std::int32_t {
    Nv12 = 0,
    P010 = 1,
    Bgra8 = 2,
};

struct GpuFrameProcessorConfig {
    std::uint32_t target_width = 0;  // zero means the post-rotation source width
    std::uint32_t target_height = 0; // zero means the post-rotation source height
    GpuPixelFormat output_format = GpuPixelFormat::Nv12;
    RECT crop{};                     // empty means the complete source texture
    DXGI_MODE_ROTATION rotation = DXGI_MODE_ROTATION_IDENTITY;
};

struct GpuFrameProcessorStats {
    std::uint64_t gpu_preprocess_frames = 0;
    std::uint64_t frames_replaced = 0;
    std::uint64_t resolution_changes = 0;
    // CPU time spent validating and submitting work. This is deliberately not a
    // blocking GPU completion measurement.
    double preprocess_latency_ms = 0.0;
};

// GPU-only D3D11 video processing stage. The caller supplies capture textures and
// receives AddRef'd pooled output textures. It must Release every returned texture.
class GpuFrameProcessor {
public:
    GpuFrameProcessor();
    ~GpuFrameProcessor();
    GpuFrameProcessor(const GpuFrameProcessor&) = delete;
    GpuFrameProcessor& operator=(const GpuFrameProcessor&) = delete;

    int32_t configure(const GpuFrameProcessorConfig& config);
    int32_t process_frame(ID3D11Texture2D* capture_texture, std::uint64_t frame_id);
    int32_t get_latest_frame(ID3D11Texture2D** texture, std::uint64_t* frame_id);
    int32_t get_stats(GpuFrameProcessorStats& stats) const;
    void reset();

private:
    class State;
    std::unique_ptr<State> state_;
};

} // namespace snowlink
