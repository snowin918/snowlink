#include "snowlink/capture.h"

#include <Windows.h>
#include <d3d11.h>
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <thread>

int wmain(int argc, wchar_t** argv) {
    int monitor = 0;
    int seconds = 10;
    bool cursor = false;
    int backend = static_cast<int>(snowlink::CaptureBackend::Auto);
    for (int i = 1; i < argc; ++i) {
        const std::wstring arg = argv[i];
        if (arg == L"--monitor" && i + 1 < argc) monitor = _wtoi(argv[++i]);
        else if (arg == L"--seconds" && i + 1 < argc) seconds = std::max(1, _wtoi(argv[++i]));
        else if (arg == L"--cursor") cursor = true;
        else if (arg == L"--backend" && i + 1 < argc) {
            const std::wstring value = argv[++i];
            if (value == L"auto") backend = -1;
            else if (value == L"dxgi") backend = 0;
            else if (value == L"wgc") backend = 1;
            else { std::wcerr << L"invalid backend\n"; return 2; }
        }
        else {
            std::wcerr << L"usage: snowlink_capture_test [--backend auto|wgc|dxgi] [--monitor N] [--seconds N] [--cursor]\n";
            return 2;
        }
    }

    snowlink::CaptureManager capture;
    capture.set_capture_cursor_in_video(cursor);
    snowlink::CaptureConfig config{};
    config.backend = backend;
    config.monitor_index = monitor;
    const int32_t result = capture.start(config);
    if (result != 0) {
        std::cerr << "capture start failed: " << result << "\n";
        return 1;
    }

    const auto started = std::chrono::steady_clock::now();
    uint64_t observed = 0;
    uint64_t last_id = 0;
    auto next_report = started + std::chrono::seconds(1);
    uint64_t last_report_frames = 0;
    while (std::chrono::steady_clock::now() - started < std::chrono::seconds(seconds)) {
        ID3D11Texture2D* texture = nullptr;
        uint64_t id = 0;
        snowlink::FrameMetadata metadata;
        snowlink::PointerState pointer;
        if (capture.get_latest_frame(&texture, &id, &metadata, &pointer) == 0) {
            // Deliberately inspect only GPU metadata; never Map or copy to staging.
            if (id != last_id) { ++observed; last_id = id; }
            texture->Release();
        }
        if (std::chrono::steady_clock::now() >= next_report) {
            snowlink::CaptureBackendStats periodic{}; capture.get_stats(periodic);
            std::cout << "fps=" << (periodic.frames_captured - last_report_frames)
                      << " dirty=" << periodic.dirty_rects << " moves=" << periodic.move_rects
                      << " cursor_updates=" << periodic.pointer_updates << "\n";
            last_report_frames = periodic.frames_captured;
            next_report += std::chrono::seconds(1);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    snowlink::CaptureStatus status{};
    snowlink::CaptureBackendStats stats{};
    capture.get_capture_status(status);
    capture.get_stats(stats);
    capture.stop();
    const double elapsed = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - started).count();
    std::cout << "frames=" << stats.frames_captured
              << " observed=" << observed
              << " fps=" << (stats.frames_captured / elapsed)
              << " resolution=" << status.width << "x" << status.height
              << " replaced=" << stats.frames_replaced
              << " recreates=" << stats.frame_pool_recreates
              << " backend=" << (status.backend == 1 ? "wgc" : "dxgi")
              << " rotation=" << static_cast<int>(status.rotation)
              << " dirty=" << stats.dirty_rects
              << " moves=" << stats.move_rects
              << " cursor_updates=" << stats.pointer_updates
              << " timeouts=" << stats.timeouts
              << " recoveries=" << stats.access_lost_recoveries
              << " borderless_available=" << status.borderless_capture_available
              << " borderless_granted=" << status.borderless_capture_granted
              << " border_active=" << status.capture_border_active
              << " cursor_in_video=" << status.capture_cursor_in_video << "\n";
    return stats.frames_captured ? 0 : 3;
}
