"""Windows WASAPI audio endpoint enumeration via PyAudioWPatch."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import Any, Literal

from snowlink.media.audio_errors import AudioError, failure_for

DeviceKind = Literal[
    "physical_output",
    "wasapi_loopback",
    "microphone_or_input",
    "virtual_audio",
    "unavailable",
    "other",
]


@dataclass(frozen=True, slots=True)
class AudioEndpointInfo:
    """One PortAudio / WASAPI device with Snowlink classification."""

    index: int
    name: str
    host_api: str
    host_api_index: int
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    is_wasapi: bool
    is_loopback: bool
    associated_output_name: str | None
    associated_output_index: int | None
    is_default_output: bool
    is_default_input: bool
    can_capture: bool
    can_playback: bool
    kind: DeviceKind
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_windows() -> bool:
    return sys.platform == "win32"


def require_pyaudio() -> Any:
    try:
        import pyaudiowpatch as pyaudio  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        raise AudioError(
            failure_for(
                "PYAUDIO_WPATCH_NOT_INSTALLED",
                "PyAudioWPatch is not installed in this environment.",
                exception=exc,
            )
        ) from exc
    return pyaudio


def _host_api_name(pa: Any, pyaudio: Any, host_api_index: int) -> tuple[str, bool]:
    try:
        info = pa.get_host_api_info_by_index(host_api_index)
        name = str(info.get("name", f"host-{host_api_index}"))
        is_wasapi = False
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            is_wasapi = int(info.get("index", -1)) == int(wasapi.get("index", -2))
        except Exception:
            is_wasapi = "wasapi" in name.lower()
        return name, is_wasapi
    except Exception:
        return f"host-{host_api_index}", False


def _looks_virtual(name: str) -> bool:
    lower = name.lower()
    needles = (
        "cable",
        "vb-audio",
        "voicemeeter",
        "virtual",
        "steam streaming",
        "nvidia broadcast",
        "obs",
        "wave link",
        "discord",
    )
    return any(n in lower for n in needles)


def _classify(
    *,
    name: str,
    is_wasapi: bool,
    is_loopback: bool,
    max_in: int,
    max_out: int,
    available: bool,
) -> DeviceKind:
    if not available:
        return "unavailable"
    if is_loopback:
        return "wasapi_loopback"
    if _looks_virtual(name):
        return "virtual_audio"
    if max_out > 0 and max_in == 0:
        return "physical_output"
    if max_in > 0 and max_out == 0:
        return "microphone_or_input"
    if max_out > 0:
        return "physical_output"
    if max_in > 0:
        return "microphone_or_input"
    return "other"


def enumerate_audio_endpoints(pa: Any | None = None) -> list[AudioEndpointInfo]:
    """Enumerate all PortAudio devices with WASAPI/loopback metadata."""
    if not is_windows():
        raise AudioError(
            failure_for(
                "WASAPI_NOT_AVAILABLE",
                "Audio endpoint enumeration for Experiment D requires Windows.",
            )
        )
    pyaudio = require_pyaudio()
    owns = pa is None
    if pa is None:
        pa = pyaudio.PyAudio()

    try:
        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception as exc:
            raise AudioError(
                failure_for(
                    "WASAPI_NOT_AVAILABLE",
                    "WASAPI host API is not available on this system.",
                    exception=exc,
                )
            ) from exc

        default_out = int(wasapi_info.get("defaultOutputDevice", -1))
        default_in = int(wasapi_info.get("defaultInputDevice", -1))

        # Build loopback → associated output name map.
        loopbacks: list[dict[str, Any]] = []
        try:
            for lb in pa.get_loopback_device_info_generator():
                loopbacks.append(dict(lb))
        except Exception:
            loopbacks = []

        devices: list[AudioEndpointInfo] = []
        count = int(pa.get_device_count())
        for index in range(count):
            try:
                info = dict(pa.get_device_info_by_index(index))
            except Exception:
                devices.append(
                    AudioEndpointInfo(
                        index=index,
                        name=f"<unavailable {index}>",
                        host_api="unknown",
                        host_api_index=-1,
                        max_input_channels=0,
                        max_output_channels=0,
                        default_sample_rate=0.0,
                        is_wasapi=False,
                        is_loopback=False,
                        associated_output_name=None,
                        associated_output_index=None,
                        is_default_output=False,
                        is_default_input=False,
                        can_capture=False,
                        can_playback=False,
                        kind="unavailable",
                        available=False,
                    )
                )
                continue

            host_idx = int(info.get("hostApi", -1))
            host_name, is_wasapi = _host_api_name(pa, pyaudio, host_idx)
            is_loopback = bool(info.get("isLoopbackDevice", False))
            max_in = int(info.get("maxInputChannels", 0) or 0)
            max_out = int(info.get("maxOutputChannels", 0) or 0)
            name = str(info.get("name", f"device-{index}"))
            rate = float(info.get("defaultSampleRate", 0.0) or 0.0)

            assoc_name: str | None = None
            assoc_index: int | None = None
            if is_loopback:
                # Strip common "[Loopback]" suffix hints for association display.
                base = name.replace("[Loopback]", "").replace("(Loopback)", "").strip()
                assoc_name = base or name
                for out_idx in range(count):
                    try:
                        out_info = pa.get_device_info_by_index(out_idx)
                    except Exception:
                        continue
                    if bool(out_info.get("isLoopbackDevice", False)):
                        continue
                    if int(out_info.get("maxOutputChannels", 0) or 0) < 1:
                        continue
                    out_name = str(out_info.get("name", ""))
                    if out_name and out_name in name:
                        assoc_name = out_name
                        assoc_index = out_idx
                        break

            can_capture = is_loopback and max_in > 0
            can_playback = (not is_loopback) and max_out > 0
            kind = _classify(
                name=name,
                is_wasapi=is_wasapi,
                is_loopback=is_loopback,
                max_in=max_in,
                max_out=max_out,
                available=True,
            )
            devices.append(
                AudioEndpointInfo(
                    index=index,
                    name=name,
                    host_api=host_name,
                    host_api_index=host_idx,
                    max_input_channels=max_in,
                    max_output_channels=max_out,
                    default_sample_rate=rate,
                    is_wasapi=is_wasapi,
                    is_loopback=is_loopback,
                    associated_output_name=assoc_name,
                    associated_output_index=assoc_index,
                    is_default_output=(index == default_out),
                    is_default_input=(index == default_in),
                    can_capture=can_capture,
                    can_playback=can_playback,
                    kind=kind,
                    available=True,
                )
            )
        # Silence unused variable if loopbacks empty path kept for future.
        _ = loopbacks
        return devices
    finally:
        if owns:
            try:
                pa.terminate()
            except Exception:
                pass


def resolve_loopback_device(
    selector: str,
    *,
    pa: Any | None = None,
    endpoints: list[AudioEndpointInfo] | None = None,
) -> AudioEndpointInfo:
    """Resolve ``default`` or a device index to a WASAPI loopback endpoint.

    Never selects a microphone for system-audio capture.
    """
    pyaudio = require_pyaudio()
    owns = pa is None
    if pa is None:
        pa = pyaudio.PyAudio()
    try:
        devices = endpoints or enumerate_audio_endpoints(pa)
        key = selector.strip().lower()
        if key == "default":
            try:
                lb = pa.get_default_wasapi_loopback()
                index = int(lb["index"])
                for d in devices:
                    if d.index == index and d.is_loopback:
                        return d
                # Fall through to rebuild from raw dict.
                return AudioEndpointInfo(
                    index=index,
                    name=str(lb.get("name", "default-loopback")),
                    host_api="Windows WASAPI",
                    host_api_index=int(lb.get("hostApi", -1)),
                    max_input_channels=int(lb.get("maxInputChannels", 0) or 0),
                    max_output_channels=int(lb.get("maxOutputChannels", 0) or 0),
                    default_sample_rate=float(lb.get("defaultSampleRate", 0.0) or 0.0),
                    is_wasapi=True,
                    is_loopback=True,
                    associated_output_name=str(lb.get("name", "")),
                    associated_output_index=None,
                    is_default_output=False,
                    is_default_input=False,
                    can_capture=True,
                    can_playback=False,
                    kind="wasapi_loopback",
                )
            except LookupError as exc:
                raise AudioError(
                    failure_for(
                        "NO_LOOPBACK_DEVICE",
                        "Default WASAPI loopback endpoint was not found.",
                        exception=exc,
                    )
                ) from exc
            except OSError as exc:
                raise AudioError(
                    failure_for(
                        "WASAPI_NOT_AVAILABLE",
                        "WASAPI is not available.",
                        exception=exc,
                    )
                ) from exc

        if not key.isdigit():
            raise AudioError(
                failure_for(
                    "INVALID_CAPTURE_DEVICE",
                    f"Capture device must be 'default' or an integer index, got {selector!r}.",
                )
            )
        index = int(key)
        for d in devices:
            if d.index == index:
                if not d.is_loopback or not d.can_capture:
                    raise AudioError(
                        failure_for(
                            "INVALID_CAPTURE_DEVICE",
                            f"Device {index} ({d.name!r}) is not a WASAPI loopback "
                            "capture endpoint. Do not select a microphone for "
                            "system-audio capture.",
                        )
                    )
                return d
        raise AudioError(
            failure_for(
                "INVALID_CAPTURE_DEVICE",
                f"Capture device index {index} was not found. Re-run `list`.",
            )
        )
    finally:
        if owns:
            try:
                pa.terminate()
            except Exception:
                pass


def resolve_playback_device(
    selector: str,
    *,
    pa: Any | None = None,
    endpoints: list[AudioEndpointInfo] | None = None,
) -> AudioEndpointInfo:
    """Resolve ``default`` or a device index to a playback-capable output."""
    pyaudio = require_pyaudio()
    owns = pa is None
    if pa is None:
        pa = pyaudio.PyAudio()
    try:
        devices = endpoints or enumerate_audio_endpoints(pa)
        key = selector.strip().lower()
        if key == "default":
            try:
                wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                index = int(wasapi["defaultOutputDevice"])
            except Exception as exc:
                raise AudioError(
                    failure_for(
                        "WASAPI_NOT_AVAILABLE",
                        "Could not resolve the default WASAPI output device.",
                        exception=exc,
                    )
                ) from exc
            for d in devices:
                if d.index == index and d.can_playback:
                    return d
            # Fallback: first WASAPI playback device.
            for d in devices:
                if d.is_wasapi and d.can_playback:
                    return d
            raise AudioError(
                failure_for(
                    "INVALID_PLAYBACK_DEVICE",
                    "Default WASAPI playback device was not found.",
                )
            )

        if not key.isdigit():
            raise AudioError(
                failure_for(
                    "INVALID_PLAYBACK_DEVICE",
                    f"Playback device must be 'default' or an integer index, got {selector!r}.",
                )
            )
        index = int(key)
        for d in devices:
            if d.index == index:
                if not d.can_playback:
                    raise AudioError(
                        failure_for(
                            "INVALID_PLAYBACK_DEVICE",
                            f"Device {index} ({d.name!r}) cannot be used for playback.",
                        )
                    )
                return d
        raise AudioError(
            failure_for(
                "INVALID_PLAYBACK_DEVICE",
                f"Playback device index {index} was not found. Re-run `list`.",
            )
        )
    finally:
        if owns:
            try:
                pa.terminate()
            except Exception:
                pass


def feedback_risk_warnings(
    capture: AudioEndpointInfo,
    playback: AudioEndpointInfo,
) -> list[str]:
    """Return human warnings when capture/playback may create a feedback loop."""
    warnings: list[str] = []
    cap_assoc = (capture.associated_output_name or capture.name).lower()
    play_name = playback.name.lower()
    same = (
        capture.associated_output_index is not None
        and capture.associated_output_index == playback.index
    ) or (play_name and play_name in cap_assoc) or (cap_assoc and cap_assoc in play_name)
    if same:
        warnings.append(
            "WARNING: Capture and playback appear to use the same physical output. "
            "This can create an echo/feedback loop. Prefer headphones."
        )
    warnings.append(
        "WARNING: Use headphones when possible. Playing loopback through speakers "
        "near an open microphone path can create feedback. This program does not "
        "change Windows master volume."
    )
    return warnings


def format_endpoint_list(devices: list[AudioEndpointInfo]) -> str:
    """Human-readable grouped device listing."""
    groups: dict[str, list[AudioEndpointInfo]] = {
        "WASAPI loopback capture endpoints": [],
        "Physical output devices": [],
        "Microphones / ordinary input devices": [],
        "Virtual audio devices": [],
        "Unavailable / other": [],
    }
    for d in devices:
        if d.kind == "wasapi_loopback":
            groups["WASAPI loopback capture endpoints"].append(d)
        elif d.kind == "physical_output":
            groups["Physical output devices"].append(d)
        elif d.kind == "microphone_or_input":
            groups["Microphones / ordinary input devices"].append(d)
        elif d.kind == "virtual_audio":
            groups["Virtual audio devices"].append(d)
        else:
            groups["Unavailable / other"].append(d)

    lines = [f"Audio endpoints found: {len(devices)}", "-" * 72]
    for title, items in groups.items():
        lines.append(f"{title} ({len(items)})")
        if not items:
            lines.append("  (none)")
            lines.append("")
            continue
        for d in items:
            flags: list[str] = []
            if d.is_default_output:
                flags.append("DEFAULT_OUTPUT")
            if d.is_default_input:
                flags.append("DEFAULT_INPUT")
            if d.can_capture:
                flags.append("CAPTURE")
            if d.can_playback:
                flags.append("PLAYBACK")
            if d.is_loopback:
                flags.append("LOOPBACK")
            if d.is_wasapi:
                flags.append("WASAPI")
            flag_s = ", ".join(flags) if flags else "-"
            lines.append(f"  [{d.index}] {d.name}")
            lines.append(
                f"      host_api={d.host_api}  in={d.max_input_channels}  "
                f"out={d.max_output_channels}  rate={d.default_sample_rate:.0f}  "
                f"kind={d.kind}"
            )
            if d.associated_output_name:
                assoc = d.associated_output_name
                if d.associated_output_index is not None:
                    assoc = f"{assoc} (index {d.associated_output_index})"
                lines.append(f"      associated_output={assoc}")
            lines.append(f"      flags=[{flag_s}]")
        lines.append("")
    lines.append(
        "System-audio capture must use a LOOPBACK endpoint (not a microphone)."
    )
    return "\n".join(lines) + "\n"


def pa_format_name(pyaudio: Any, fmt: int) -> str:
    mapping = {
        int(pyaudio.paFloat32): "float32",
        int(pyaudio.paInt16): "int16",
        int(pyaudio.paInt32): "int32",
        int(pyaudio.paInt8): "int8",
        int(pyaudio.paUInt8): "uint8",
    }
    return mapping.get(int(fmt), "unknown")
