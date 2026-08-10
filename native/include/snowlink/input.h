#pragma once
#include <cstdint>
#include <vector>

namespace snowlink {
enum class InputKind : std::uint8_t { MouseMove=1, MouseButton=2, Wheel=3, Key=4 };
enum class MouseButton : std::uint8_t { Left=1, Right=2, Middle=3, X1=4, X2=5 };
struct RemoteInputEvent {
    InputKind kind = InputKind::MouseMove;
    std::uint8_t code = 0;       // button or virtual-key
    bool down = false;
    std::int32_t x = 0, y = 0;  // source-content coordinates
    std::int32_t delta = 0;     // wheel delta
    std::uint64_t sequence = 0;
};
class InputSubsystem {
public:
    InputSubsystem(); ~InputSubsystem();
    int32_t initialize();
    void set_authorized(bool authorized) noexcept;
    void set_source_desktop(std::int32_t left, std::int32_t top,
                            std::uint32_t width, std::uint32_t height) noexcept;
    int32_t inject(const RemoteInputEvent& event);
    int32_t shutdown();
private:
    bool authorized_ = false;
    std::int32_t left_ = 0, top_ = 0;
    std::uint32_t width_ = 0, height_ = 0;
};
std::vector<std::uint8_t> encode_input_event(const RemoteInputEvent& event);
bool decode_input_event(const std::uint8_t* data, std::size_t size, RemoteInputEvent& event);
} // namespace snowlink
