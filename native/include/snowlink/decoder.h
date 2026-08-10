#pragma once

#include "encoder.h"
#include <d3d11.h>
#include <cstdint>
#include <memory>
#include <string>

namespace snowlink {

struct DecoderInfo {
    std::string decoder_name;
    bool hardware_accelerated = false;
    std::uint32_t decoded_width = 0;
    std::uint32_t decoded_height = 0;
    double decode_fps = 0.0;
    std::uint64_t frames_decoded = 0;
    std::uint64_t corrupt_frames = 0;
};

class IVideoDecoder {
public:
    virtual ~IVideoDecoder() = default;
    virtual int32_t initialize(ID3D11Device* device) = 0;
    virtual int32_t decode(const EncodedFrame& frame, ID3D11Texture2D** texture,
                           std::uint32_t* subresource_index) = 0;
    virtual int32_t reset() = 0;
    virtual void shutdown() = 0;
    virtual const DecoderInfo& info() const noexcept = 0;
};

// Hardware-only Media Foundation H.264 decoder. Output samples are DXGI-backed
// NV12 textures allocated by the MFT on the caller's D3D11 device.
class H264HardwareDecoder final : public IVideoDecoder {
public:
    H264HardwareDecoder();
    ~H264HardwareDecoder() override;
    int32_t initialize(ID3D11Device* device) override;
    int32_t decode(const EncodedFrame& frame, ID3D11Texture2D** texture,
                   std::uint32_t* subresource_index) override;
    int32_t reset() override;
    void shutdown() override;
    const DecoderInfo& info() const noexcept override;
private:
    class State;
    std::unique_ptr<State> state_;
};

} // namespace snowlink
