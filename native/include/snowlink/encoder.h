#pragma once

#include <d3d11.h>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace snowlink {

enum class VideoCodec : std::int32_t { H264 = 0 };
enum class RateControlMode : std::int32_t { Cbr = 0, Vbr = 1 };
enum class HardwarePreference : std::int32_t {
    RequireHardware = 0,
    PreferHardware = 1,
    AllowSoftwareFallback = 2,
};

struct EncoderSettings {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t fps = 60;
    std::uint32_t bitrate = 8'000'000;
    std::uint32_t keyframe_interval = 120; // frames
    bool low_latency = true;
    RateControlMode rate_control = RateControlMode::Cbr;
    HardwarePreference hardware_preference = HardwarePreference::RequireHardware;
};

struct EncoderInfo {
    std::string encoder_name;
    std::string encoder_vendor;
    std::string failure_stage;
    bool hardware_accelerated = false;
    std::string codec = "H.264";
    std::string profile;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t fps = 0;
    std::uint32_t bitrate = 0;
};

struct EncodedFrame {
    std::uint64_t timestamp = 0; // caller's 100-nanosecond media timestamp
    bool keyframe = false;
    VideoCodec codec = VideoCodec::H264;
    std::vector<std::uint8_t> bytes;
};

class IVideoEncoder {
public:
    virtual ~IVideoEncoder() = default;
    virtual int32_t initialize(ID3D11Device* device, const EncoderSettings& settings) = 0;
    virtual int32_t encode(ID3D11Texture2D* texture, std::uint64_t timestamp,
                           std::vector<EncodedFrame>& output) = 0;
    virtual int32_t poll(std::vector<EncodedFrame>& output) = 0;
    virtual int32_t request_keyframe() = 0;
    virtual int32_t set_bitrate(std::uint32_t bitrate) = 0;
    virtual int32_t set_fps(std::uint32_t fps) = 0;
    virtual void shutdown() = 0;
    virtual const EncoderInfo& info() const noexcept = 0;
};

// Media Foundation H.264 encoder. Input remains an NV12 D3D11 texture; only the
// compressed output buffer is CPU-addressed. Instances are not thread safe.
class H264HardwareEncoder final : public IVideoEncoder {
public:
    H264HardwareEncoder();
    ~H264HardwareEncoder() override;
    H264HardwareEncoder(const H264HardwareEncoder&) = delete;
    H264HardwareEncoder& operator=(const H264HardwareEncoder&) = delete;

    int32_t initialize(ID3D11Device* device, const EncoderSettings& settings) override;
    int32_t encode(ID3D11Texture2D* texture, std::uint64_t timestamp,
                   std::vector<EncodedFrame>& output) override;
    int32_t poll(std::vector<EncodedFrame>& output) override;
    int32_t request_keyframe() override;
    int32_t set_bitrate(std::uint32_t bitrate) override;
    int32_t set_fps(std::uint32_t fps) override;
    void shutdown() override;
    const EncoderInfo& info() const noexcept override;

private:
    class State;
    std::unique_ptr<State> state_;
};

} // namespace snowlink
