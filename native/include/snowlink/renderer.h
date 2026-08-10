#pragma once
#include <d3d11.h>
#include <Windows.h>
#include <cstdint>
#include <memory>

namespace snowlink {

struct RendererStats { double render_fps = 0.0; std::uint64_t frames_presented = 0; std::uint64_t frames_replaced = 0; };

class Renderer {
public:
    Renderer(); ~Renderer();
    int32_t initialize(HWND window, ID3D11Device* device);
    int32_t submit(ID3D11Texture2D* texture, std::uint32_t subresource_index,
                   std::uint64_t frame_id);
    int32_t resize();
    int32_t set_visible(bool visible);
    int32_t get_stats(RendererStats& stats) const;
    int32_t shutdown();
private:
    class State; std::unique_ptr<State> state_;
};
} // namespace snowlink
