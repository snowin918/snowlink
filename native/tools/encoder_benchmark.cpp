#include "snowlink/capture.h"
#include "snowlink/encoder.h"
#include "snowlink/gpu_frame_processor.h"

#include <Windows.h>
#include <algorithm>
#include <chrono>
#include <iostream>
#include <string>
#include <thread>

namespace {
double cpu_seconds(FILETIME a, FILETIME b) {
    ULARGE_INTEGER x{}, y{}; x.LowPart = a.dwLowDateTime; x.HighPart = a.dwHighDateTime;
    y.LowPart = b.dwLowDateTime; y.HighPart = b.dwHighDateTime;
    return static_cast<double>(y.QuadPart - x.QuadPart) / 10'000'000.0;
}
}

int wmain(int argc, wchar_t** argv) {
    int monitor = 0, seconds = 10, backend = -1, width = 1920, height = 1080, fps = 60;
    uint32_t bitrate = 8'000'000; bool allow_software = false;
    for (int i = 1; i < argc; ++i) {
        std::wstring arg = argv[i];
        if (arg == L"--monitor" && i + 1 < argc) monitor = _wtoi(argv[++i]);
        else if (arg == L"--seconds" && i + 1 < argc) seconds = std::max(1, _wtoi(argv[++i]));
        else if (arg == L"--fps" && i + 1 < argc) fps = std::max(1, _wtoi(argv[++i]));
        else if (arg == L"--bitrate" && i + 1 < argc) bitrate = static_cast<uint32_t>(_wtoi(argv[++i]));
        else if (arg == L"--target" && i + 2 < argc) { width = _wtoi(argv[++i]); height = _wtoi(argv[++i]); }
        else if (arg == L"--allow-software") allow_software = true;
        else if (arg == L"--backend" && i + 1 < argc) {
            std::wstring v = argv[++i]; backend = v == L"wgc" ? 1 : v == L"dxgi" ? 0 : v == L"auto" ? -1 : -99;
        } else { std::wcerr << L"usage: snowlink_encoder_benchmark [--backend auto|wgc|dxgi] [--monitor N] [--seconds N] [--target W H] [--fps N] [--bitrate BPS] [--allow-software]\n"; return 2; }
    }
    if (backend == -99 || width <= 0 || height <= 0 || (width & 1) || (height & 1) || !bitrate) return 2;
    snowlink::CaptureManager capture; snowlink::CaptureConfig cc{}; cc.backend = backend; cc.monitor_index = monitor;
    int32_t hr = capture.start(cc); if (hr) { std::cerr << "capture start failed: " << hr << "\n"; return 1; }
    snowlink::GpuFrameProcessor processor; snowlink::GpuFrameProcessorConfig pc{};
    pc.target_width = static_cast<uint32_t>(width); pc.target_height = static_cast<uint32_t>(height);
    processor.configure(pc);
    snowlink::H264HardwareEncoder encoder; bool encoder_ready = false;
    uint64_t last_id = 0, encoded = 0, bytes = 0, keys = 0, dropped = 0;
    uint64_t last_capture = 0, last_encoded = 0, last_bytes = 0, last_keys = 0;
    const auto start = std::chrono::steady_clock::now(); auto report = start + std::chrono::seconds(1);
    FILETIME create{}, exit{}, kernel0{}, user0{}; GetProcessTimes(GetCurrentProcess(), &create, &exit, &kernel0, &user0);
    auto cpu_mark = start;
    while (std::chrono::steady_clock::now() - start < std::chrono::seconds(seconds)) {
        ID3D11Texture2D* capture_texture = nullptr; uint64_t id = 0; snowlink::FrameMetadata meta; snowlink::PointerState pointer;
        if (capture.get_latest_frame(&capture_texture, &id, &meta, &pointer) == 0) {
            if (id != last_id) {
                last_id = id; snowlink::CaptureStatus cs{}; capture.get_capture_status(cs); pc.rotation = cs.rotation; processor.configure(pc);
                hr = processor.process_frame(capture_texture, id);
                ID3D11Texture2D* nv12 = nullptr; uint64_t processed_id = 0;
                if (!hr) hr = processor.get_latest_frame(&nv12, &processed_id);
                if (!hr && !encoder_ready) {
                    ID3D11Device* device = nullptr; nv12->GetDevice(&device);
                    snowlink::EncoderSettings es{}; es.width = width; es.height = height; es.fps = fps; es.bitrate = bitrate;
                    es.keyframe_interval = static_cast<uint32_t>(fps * 2);
                    es.hardware_preference = allow_software ? snowlink::HardwarePreference::AllowSoftwareFallback : snowlink::HardwarePreference::RequireHardware;
                    hr = encoder.initialize(device, es); device->Release();
                    if (!hr) { encoder_ready = true; const auto& info = encoder.info(); std::cout << "selected encoder=\"" << info.encoder_name << "\" vendor=" << info.encoder_vendor << " hardware=" << (info.hardware_accelerated ? "true" : "false") << " codec=" << info.codec << " profile=" << info.profile << " " << info.width << "x" << info.height << " fps=" << info.fps << " bitrate=" << info.bitrate << "\n"; }
                }
                if (SUCCEEDED(hr) && encoder_ready) {
                    std::vector<snowlink::EncodedFrame> frames;
                    const uint64_t timestamp = std::chrono::duration_cast<std::chrono::duration<uint64_t, std::ratio<1, 10'000'000>>>(std::chrono::steady_clock::now() - start).count();
                    hr = encoder.encode(nv12, timestamp, frames);
                    if (hr == S_FALSE) { ++dropped; hr = S_OK; }
                    for (const auto& f : frames) { ++encoded; bytes += f.bytes.size(); if (f.keyframe) ++keys; }
                }
                if (nv12) nv12->Release();
                if (FAILED(hr)) { ++dropped; std::cerr << "pipeline failed: " << hr << "\n"; capture_texture->Release(); break; }
            }
            capture_texture->Release();
        }
        const auto now = std::chrono::steady_clock::now();
        if (now >= report) {
            snowlink::CaptureBackendStats stats{}; capture.get_stats(stats);
            FILETIME k{}, u{}; GetProcessTimes(GetCurrentProcess(), &create, &exit, &k, &u);
            const double wall = std::chrono::duration<double>(now - cpu_mark).count();
            const double cpu = 100.0 * (cpu_seconds(kernel0, k) + cpu_seconds(user0, u)) / wall;
            std::cout << "capture_fps=" << (stats.frames_captured - last_capture) << " encode_fps=" << (encoded - last_encoded)
                      << " encoded_mbps=" << ((bytes - last_bytes) * 8.0 / 1'000'000.0) << " keyframes=" << (keys - last_keys)
                      << " dropped=" << dropped << " encoder=\"" << (encoder_ready ? encoder.info().encoder_name : "not selected")
                      << "\" hardware=" << (encoder_ready && encoder.info().hardware_accelerated ? "true" : "false") << " cpu_percent=" << cpu << "\n";
            last_capture = stats.frames_captured; last_encoded = encoded; last_bytes = bytes; last_keys = keys;
            kernel0 = k; user0 = u; cpu_mark = now; report += std::chrono::seconds(1);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    capture.stop(); encoder.shutdown();
    return encoder_ready && encoded ? 0 : 3;
}
