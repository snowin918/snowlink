#pragma once

#include <Windows.h>
#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

namespace snowlink {

enum class CursorPixelFormat : std::uint8_t { Bgra32 = 1 };

struct CursorState {
    std::int32_t x = 0, y = 0;
    bool visible = false;
    std::uint64_t shape_id = 0;
    std::int16_t hotspot_x = 0, hotspot_y = 0;
    std::uint64_t timestamp = 0;
};

struct CursorShape {
    std::uint64_t shape_id = 0;
    std::uint16_t width = 0, height = 0;
    std::int16_t hotspot_x = 0, hotspot_y = 0;
    CursorPixelFormat format = CursorPixelFormat::Bgra32;
    std::vector<std::uint8_t> pixels;
};

// Polling is deliberately independent of capture/video cadence.  The callback
// receives a shape only when its content hash changes.
class CursorSubsystem {
public:
    using StateCallback = std::function<void(const CursorState&)>;
    using ShapeCallback = std::function<void(const CursorShape&)>;
    CursorSubsystem(); ~CursorSubsystem();
    int32_t initialize_sender(RECT source_desktop, StateCallback, ShapeCallback);
    int32_t initialize_receiver(HWND video_window, std::uint32_t source_width,
                                std::uint32_t source_height);
    int32_t update_source_size(std::uint32_t width, std::uint32_t height);
    int32_t receive_state(const CursorState& state);
    int32_t receive_shape(const CursorShape& shape);
    int32_t shutdown();
private:
    class State; std::unique_ptr<State> state_;
};

std::vector<std::uint8_t> encode_cursor_state(const CursorState& state);
std::vector<std::uint8_t> encode_cursor_shape(const CursorShape& shape);
bool decode_cursor_message(const std::uint8_t* data, std::size_t size,
                           CursorState* state, CursorShape* shape);
} // namespace snowlink
