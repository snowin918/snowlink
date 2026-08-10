"""Two-process, native-only Snowlink media loopback acceptance harness.

The parent exchanges SDP between an isolated sender and receiver process. Video
capture, H.264, RTP/DTLS/ICE, decode, and D3D presentation all stay native.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import queue
import sys
import time
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _wait_message(channel: Any, timeout_s: float) -> dict[str, Any]:
    try:
        value = channel.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise TimeoutError("timed out waiting for peer process") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid peer message: {value!r}")
    return value


def _wait_description(engine: Any, timeout_s: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        description = engine.local_description()
        if description is not None:
            return description
        time.sleep(0.02)
    raise TimeoutError("native ICE gathering timed out")


def _sender(to_receiver: Any, from_receiver: Any, results: Any, duration_s: float) -> None:
    from snowlink.native_engine import NativeEngine

    engine = NativeEngine.create()
    try:
        engine.initialize()
        engine.start_capture(monitor_index=0, target_fps=30, backend=0)
        engine.connect(bind_address="127.0.0.1", port_min=41000, port_max=41099)
        engine.create_offer()
        to_receiver.put({"kind": "offer", **_wait_description(engine, 15.0)})
        answer = _wait_message(from_receiver, 20.0)
        engine.set_remote_description(sdp=answer["sdp"], sdp_type=answer["type"])
        deadline = time.monotonic() + 15.0
        while True:
            try:
                engine.start_stream(width=854, height=480, target_fps=30, bitrate_bps=2_500_000)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        end = time.monotonic() + duration_s
        last = None
        while time.monotonic() < end:
            last = engine.get_stats()
            print(
                "SENDER"
                f" captured={last.frames_captured} encoded={last.frames_encoded}"
                f" packets={last.packets_sent} bitrate={last.send_bitrate:.0f}"
                f" drops={last.frames_dropped + last.transport_frames_dropped}"
                f" error={engine.last_error() or 'none'}",
                flush=True,
            )
            time.sleep(1.0)
        assert last is not None
        passed = last.frames_encoded > 0 and last.packets_sent > 0
        results.put({"role": "sender", "passed": passed, "stats": repr(last)})
    except BaseException as exc:
        results.put(
            {
                "role": "sender",
                "passed": False,
                "error": repr(exc),
                "trace": traceback.format_exc(),
            }
        )
    finally:
        try:
            engine.shutdown()
        finally:
            engine.destroy()


def _receiver(to_sender: Any, from_sender: Any, results: Any, duration_s: float) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget

    from snowlink.native_engine import NativeEngine

    app = QApplication(["snowlink-native-loopback-viewer"])
    surface = QWidget()
    surface.setWindowTitle("Snowlink native loopback viewer")
    surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    surface.resize(854, 480)
    surface.show()
    app.processEvents()
    engine = NativeEngine.create()
    try:
        engine.initialize()
        engine.start_receiver(hwnd=int(surface.winId()), bind_address="127.0.0.1")
        offer = _wait_message(from_sender, 20.0)
        engine.set_remote_description(sdp=offer["sdp"], sdp_type=offer["type"])
        engine.create_receiver_answer()
        to_sender.put({"kind": "answer", **_wait_description(engine, 15.0)})
        engine.receiver_set_visible(True)
        engine.receiver_resize()
        end = time.monotonic() + duration_s
        last = None
        tick = 0
        while time.monotonic() < end:
            app.processEvents()
            # Animate the local window so desktop duplication produces frames
            # even when the rest of the test desktop is static.
            surface.move(80 + (tick % 20) * 2, 80)
            tick += 1
            last = engine.get_stats()
            decoder = engine.decoder_status()
            print(
                "VIEWER"
                f" decoded={last.frames_decoded} decode_fps={last.decode_fps:.1f}"
                f" render_fps={last.render_fps:.1f}"
                f" size={decoder['decoded_width']}x{decoder['decoded_height']}"
                f" drops={last.frames_dropped} error={engine.last_error() or 'none'}",
                flush=True,
            )
            if last.frames_decoded >= 3 and last.render_fps > 0 and decoder["decoded_width"] > 0:
                results.put({"role": "receiver", "passed": True, "stats": repr(last)})
                return
            time.sleep(0.1)
        results.put({"role": "receiver", "passed": False, "stats": repr(last)})
    except BaseException as exc:
        results.put(
            {
                "role": "receiver",
                "passed": False,
                "error": repr(exc),
                "trace": traceback.format_exc(),
            }
        )
    finally:
        try:
            engine.shutdown()
        finally:
            engine.destroy()
        surface.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=20.0)
    args = parser.parse_args()
    context = mp.get_context("spawn")
    sender_to_receiver = context.Queue()
    receiver_to_sender = context.Queue()
    results = context.Queue()
    receiver = context.Process(
        name="snowlink-native-viewer",
        target=_receiver,
        args=(receiver_to_sender, sender_to_receiver, results, args.duration),
    )
    sender = context.Process(
        name="snowlink-native-sender",
        target=_sender,
        args=(sender_to_receiver, receiver_to_sender, results, args.duration),
    )
    receiver.start()
    sender.start()
    reports = [_wait_message(results, args.duration + 30.0) for _ in range(2)]
    sender.join(10.0)
    receiver.join(10.0)
    for process in (sender, receiver):
        if process.is_alive():
            process.terminate()
            process.join(5.0)
    for report in reports:
        print(f"RESULT {report}", flush=True)
    passed = all(report.get("passed") is True for report in reports)
    print("NATIVE LOOPBACK PASS" if passed else "NATIVE LOOPBACK FAIL", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
