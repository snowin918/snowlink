# Native Engine Benchmark

## Result status

One live native WGC result has now been recorded on an interactive NVIDIA system;
see below. No apples-to-apples legacy Python result, receiver latency result, or
valid DXGI throughput result has been recorded yet. The 2026-08-10 automation
session was non-interactive: WGC failed with
`0x80070424` (capture service unavailable) and DXGI Desktop Duplication failed
with `0x80070005` (`E_ACCESSDENIED`). Consequently, CPU, GPU, RAM, VRAM, FPS,
bitrate, and latency values below are deliberately marked **not measured**.

Do not use a capture-start failure or synthetic packet test as a performance
result. Run this matrix on the same two interactive Windows machines, network,
monitor, content, resolution, FPS, bitrate, and measurement interval for both
engines.

## Apples-to-apples summary

| Workload | Legacy Python | Native C++ |
|---|---:|---:|
| 1920x1080 @ 30 process CPU | not measured | not measured |
| 1920x1080 @ 60 process CPU | not measured | not measured |
| RAM | not measured | not measured |
| Capture FPS | not measured | not measured |
| Encode FPS | not measured | not measured |
| End-to-end latency | not measured | not measured |

## Measured native results

### WGC, 1920x1080 @ 30

Interactive continuous-motion run, 15 seconds, 6 Mbps target, NVIDIA H.264
Encoder MFT (`hardware=true`):

| Metric | Result |
|---|---:|
| Capture FPS | 29–31 steady |
| Process FPS | 29.3 average over reported intervals |
| Encode FPS | 29.1 average over reported intervals |
| Encoder submission drops | 0 |
| GPU preprocess CPU submission latency | 0.013–0.027 ms steady; 0.133 ms initialization interval |
| Encoder enqueue latency | 0.006–0.008 ms typical |
| Process CPU | 2.8% mean of one-second samples; samples are quantized and ranged 0–10.9% |
| Encoded bitrate | workload-dependent, approximately 4.1–7.8 Mbps per interval |

This validates native WGC capture, GPU conversion, asynchronous hardware encode,
and 30 FPS pacing on the tested machine. It does not measure network, decode,
render, or end-to-end latency.

### DXGI, 1920x1080 @ 30

Interactive variable-motion run, 15 seconds, 6 Mbps target, NVIDIA H.264
Encoder MFT (`hardware=true`), after isolating Desktop Duplication on a separate
D3D11 device with keyed-mutex shared textures:

| Metric | Result |
|---|---:|
| Capture FPS | 26–54 depending on content |
| Process FPS | 26.2 average; reached configured 30 FPS when capture supplied it |
| Encode FPS | 26.1 average; reached configured 30 FPS |
| Encoder submission drops | 0 |
| GPU preprocess CPU submission latency | 0.012–0.017 ms steady; 0.122 ms initialization interval |
| Encoder enqueue latency | 0.006–0.008 ms typical |
| Process CPU | 4.9% mean of one-second samples; samples are quantized and ranged 0–12.4% |

This validates the isolated-device DXGI capture-to-hardware-encode pipeline at
1080p30. The lower average reflects intervals where the variable-motion source
supplied fewer than 30 changed frames; no synthetic duplicate frames are added.

### 1920x1080 @ 60 capability runs

WGC and DXGI were configured for 60 FPS with the NVIDIA hardware encoder and
zero submission drops. WGC received mostly 29–42 changed frames/sec; DXGI
received 22–45. Processing and encoding tracked the supplied frames, reaching
40 FPS on WGC and 42 FPS on DXGI, with approximately 0.01–0.03 ms steady GPU
preprocess submission time. These runs validate uncapped behavior above 30 FPS
but do **not** prove sustained 60 FPS because the test content never supplied 60
changed frames/sec. A deterministic 60 Hz animation is still required.

## Required matrix

Run WGC and DXGI at 1280x720@30, 1920x1080@30, and 1920x1080@60. When the
hardware supports it, also run 2560x1440@60 and 3840x2160@30. For each setting,
exercise a static desktop, mouse movement, typing, webpage scrolling, moving
windows, video playback, and fullscreen animation. Record process CPU, GPU
engine utilization, RAM, VRAM, capture/encode/decode/render FPS, bitrate, RTT,
stage latencies, end-to-end latency, queue depth, and dropped frames.

Use `snowlink_encoder_benchmark` for capture-to-encode measurements. It prints
the selected encoder and whether it is hardware accelerated; hardware is
required unless `--allow-software` is explicitly supplied. Use Windows
Performance Recorder/GPUView or Task Manager's per-engine counters for GPU and
VRAM, and capture receiver statistics at the same cadence. Instrument latency
only in a temporary benchmark build so timestamp collection does not become a
permanent hot-path cost.

## Verified non-performance checks

The Release native build, bounded RTP/FU-A packet test, cursor/input protocol
test, and seven Python lifecycle/backend tests passed in the prior 2026-08-10
validation recorded in `native-engine-progress.md`. These establish build and
protocol behavior, not live performance.
