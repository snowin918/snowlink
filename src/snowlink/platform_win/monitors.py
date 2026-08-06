"""Windows monitor enumeration and DXcam output mapping.

Snowlink ``--monitor`` indices are **logical monitor indices** produced by this
module (primary first, then remaining monitors sorted by desktop origin). They
are **not** assumed to equal DXcam ``output_idx`` values.

Mapping policy:

1. Enumerate Win32 monitors (``EnumDisplayMonitors``) for name, DPI, primary flag,
   and desktop coordinates (which may be negative).
2. Enumerate DXcam device/output pairs with DXGI ``DesktopCoordinates``.
3. Match each logical monitor to a DXcam ``(device_idx, output_idx)`` by equal
   desktop rectangles when possible; otherwise by ``HMONITOR`` handle; otherwise
   leave DXcam indices unset and report that capture may fail for that monitor.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Any

from snowlink.media.capture_errors import CaptureError, failure_for
from snowlink.media.capture_models import KNOWN_BACKENDS


@dataclass(frozen=True, slots=True)
class DxcamOutputRef:
    """DXcam indices for a single attached output."""

    device_idx: int
    output_idx: int
    device_name: str
    adapter_name: str | None = None


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    """One logical monitor for Experiment C listing / selection."""

    index: int
    name: str
    device_name: str
    left: int
    top: int
    width: int
    height: int
    is_primary: bool
    dpi_scale: float | None
    dpi: int | None
    hmonitor: int | None
    dxcam: DxcamOutputRef | None
    backends_available: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


class MonitorEnumerationError(RuntimeError):
    """Raised when monitor enumeration is unavailable or fails."""


def is_windows() -> bool:
    """Return True when running on native Windows."""
    return sys.platform == "win32"


# --- Win32 structures / constants --------------------------------------------

MONITORINFOF_PRIMARY = 1
MDT_EFFECTIVE_DPI = 0
CCHDEVICENAME = 32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * CCHDEVICENAME),
    ]


MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)


@dataclass(slots=True)
class _RawMonitor:
    hmonitor: int
    left: int
    top: int
    right: int
    bottom: int
    is_primary: bool
    device_name: str
    name: str
    dpi: int | None
    dpi_scale: float | None


def _friendly_monitor_name(device_name: str) -> str:
    """Best-effort friendly name via SetupAPI / EnumDisplayDevices."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        # Adapter first
        if not user32.EnumDisplayDevicesW(device_name, 0, ctypes.byref(dd), 0):
            return device_name
        monitor_dd = DISPLAY_DEVICEW()
        monitor_dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if user32.EnumDisplayDevicesW(device_name, 0, ctypes.byref(monitor_dd), 0):
            # EnumDisplayDevices on the adapter device name with iDevNum=0 returns
            # the monitor attached to that adapter path in some configs; prefer
            # DeviceString when present.
            friendly = monitor_dd.DeviceString.strip()
            if friendly:
                return str(friendly)
        adapter_name = dd.DeviceString.strip()
        return str(adapter_name or device_name)
    except Exception:
        return device_name


def _query_dpi(hmonitor: int) -> tuple[int | None, float | None]:
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        hr = shcore.GetDpiForMonitor(
            wintypes.HMONITOR(hmonitor),
            MDT_EFFECTIVE_DPI,
            ctypes.byref(dpi_x),
            ctypes.byref(dpi_y),
        )
        if hr != 0:
            return None, None
        dpi = int(dpi_x.value)
        return dpi, round(dpi / 96.0, 4)
    except Exception:
        return None, None


def _enumerate_win32_monitors() -> list[_RawMonitor]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[_RawMonitor] = []

    def _callback(
        hmon: int,
        _hdc: int,
        _lprect: int,
        _lparam: int,
    ) -> int:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return 1
        device = str(info.szDevice)
        dpi, scale = _query_dpi(int(hmon))
        found.append(
            _RawMonitor(
                hmonitor=int(hmon),
                left=int(info.rcMonitor.left),
                top=int(info.rcMonitor.top),
                right=int(info.rcMonitor.right),
                bottom=int(info.rcMonitor.bottom),
                is_primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                device_name=device,
                name=_friendly_monitor_name(device),
                dpi=dpi,
                dpi_scale=scale,
            )
        )
        return 1

    enum_proc = MonitorEnumProc(_callback)
    if not user32.EnumDisplayMonitors(0, 0, enum_proc, 0):
        raise MonitorEnumerationError("EnumDisplayMonitors failed")
    # Primary first, then by desktop origin (supports negative coordinates).
    found.sort(key=lambda m: (not m.is_primary, m.left, m.top, m.device_name))
    return found


@dataclass(frozen=True, slots=True)
class _DxcamOutput:
    device_idx: int
    output_idx: int
    device_name: str
    left: int
    top: int
    right: int
    bottom: int
    hmonitor: int | None
    adapter_name: str | None
    is_primary_meta: bool | None


def _load_dxcam_outputs() -> list[_DxcamOutput]:
    """Enumerate DXcam device/output indices using public dxcam APIs.

    Uses ``enum_dxgi_adapters``, ``Device``, ``Output``, and
    ``get_output_metadata`` (all available on the ``dxcam`` package). Does not
    call private factory attributes.
    """
    try:
        import dxcam  # type: ignore[import-untyped]
    except ModuleNotFoundError:
        return []

    outputs: list[_DxcamOutput] = []
    try:
        Device = dxcam.Device
        Output = dxcam.Output
        metadata = dxcam.get_output_metadata()
        adapters = dxcam.enum_dxgi_adapters()
        device_idx = 0
        for p_adapter in adapters:
            device = Device(p_adapter)
            p_outputs = device.enum_outputs()
            if not p_outputs:
                continue
            adapter_name = None
            try:
                adapter_name = str(device.desc.Description).strip("\x00") or None
            except Exception:
                adapter_name = None
            for output_idx, p_output in enumerate(p_outputs):
                output = Output(p_output)
                rect = output.desc.DesktopCoordinates
                meta = metadata.get(output.devicename)
                is_primary = bool(meta[1]) if meta else None
                outputs.append(
                    _DxcamOutput(
                        device_idx=device_idx,
                        output_idx=output_idx,
                        device_name=str(output.devicename),
                        left=int(rect.left),
                        top=int(rect.top),
                        right=int(rect.right),
                        bottom=int(rect.bottom),
                        hmonitor=int(output.hmonitor) if output.hmonitor else None,
                        adapter_name=adapter_name,
                        is_primary_meta=is_primary,
                    )
                )
            device_idx += 1
    except Exception:
        return outputs
    return outputs

def probe_backend_availability() -> dict[str, bool]:
    """Detect which DXcam backends appear usable without capturing frames.

    Uses only public import / create probes. Unavailable backends are reported
    as False rather than raising.
    """
    availability: dict[str, bool] = {name: False for name in KNOWN_BACKENDS}
    try:
        import dxcam
    except ModuleNotFoundError:
        return availability

    normalize = getattr(dxcam, "normalize_backend_name", None)
    for name in KNOWN_BACKENDS:
        try:
            if callable(normalize):
                normalize(name)
            if name == "winrt":
                # WinRT requires optional winrt-* packages; probe import safely.
                try:
                    import dxcam.core.winrt_duplicator  # type: ignore[import-untyped]  # noqa: F401
                except Exception:
                    availability[name] = False
                    continue
            availability[name] = True
        except Exception:
            availability[name] = False
    return availability


def _match_dxcam(
    monitor: _RawMonitor,
    dxcam_outputs: list[_DxcamOutput],
) -> DxcamOutputRef | None:
    for out in dxcam_outputs:
        if (
            out.left == monitor.left
            and out.top == monitor.top
            and out.right == monitor.right
            and out.bottom == monitor.bottom
        ):
            return DxcamOutputRef(
                device_idx=out.device_idx,
                output_idx=out.output_idx,
                device_name=out.device_name,
                adapter_name=out.adapter_name,
            )
    if monitor.hmonitor is not None:
        for out in dxcam_outputs:
            if out.hmonitor is not None and out.hmonitor == monitor.hmonitor:
                return DxcamOutputRef(
                    device_idx=out.device_idx,
                    output_idx=out.output_idx,
                    device_name=out.device_name,
                    adapter_name=out.adapter_name,
                )
    # Device-name match (\\.\DISPLAYn)
    for out in dxcam_outputs:
        if out.device_name.upper() == monitor.device_name.upper():
            return DxcamOutputRef(
                device_idx=out.device_idx,
                output_idx=out.output_idx,
                device_name=out.device_name,
                adapter_name=out.adapter_name,
            )
    return None


def _enable_dpi_awareness() -> None:
    """Best-effort Per-Monitor DPI awareness for accurate desktop rectangles."""
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.WinDLL("shcore", use_last_error=True).SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.WinDLL("user32", use_last_error=True).SetProcessDPIAware()
    except Exception:
        pass


def enumerate_monitors(
    *,
    backend_probe: Callable[[], dict[str, bool]] | None = None,
) -> list[MonitorInfo]:
    """Enumerate logical monitors and map them onto DXcam outputs when possible."""
    if not is_windows():
        raise MonitorEnumerationError(
            "Monitor enumeration is only supported on Windows."
        )
    _enable_dpi_awareness()
    raw = _enumerate_win32_monitors()
    dxcam_outputs = _load_dxcam_outputs()
    backends = (backend_probe or probe_backend_availability)()
    monitors: list[MonitorInfo] = []
    for index, mon in enumerate(raw):
        mapped = _match_dxcam(mon, dxcam_outputs)
        monitors.append(
            MonitorInfo(
                index=index,
                name=mon.name,
                device_name=mon.device_name,
                left=mon.left,
                top=mon.top,
                width=mon.right - mon.left,
                height=mon.bottom - mon.top,
                is_primary=mon.is_primary,
                dpi_scale=mon.dpi_scale,
                dpi=mon.dpi,
                hmonitor=mon.hmonitor,
                dxcam=mapped,
                backends_available=dict(backends),
            )
        )
    return monitors


def get_monitor(index: int, monitors: list[MonitorInfo] | None = None) -> MonitorInfo:
    """Return the monitor at logical *index* or raise ``INVALID_MONITOR``."""
    items = monitors if monitors is not None else enumerate_monitors()
    for mon in items:
        if mon.index == index:
            return mon
    raise CaptureError(
        failure_for(
            "INVALID_MONITOR",
            f"Monitor index {index} is not available "
            f"(found {len(items)} monitor(s)).",
        )
    )


def format_monitor_list(monitors: list[MonitorInfo]) -> str:
    """Human-readable monitor listing for the Experiment C `list` command."""
    lines = [
        f"Monitors found: {len(monitors)}",
        "Index mapping: Snowlink --monitor N is a logical index (primary first), "
        "not necessarily equal to DXcam output_idx.",
        "-" * 72,
    ]
    for mon in monitors:
        dpi = (
            f"{mon.dpi} ({mon.dpi_scale}x)"
            if mon.dpi is not None and mon.dpi_scale is not None
            else "n/a"
        )
        primary = "primary" if mon.is_primary else "secondary"
        lines.append(f"[{mon.index}] {mon.name}  [{primary}]")
        lines.append(f"    device:     {mon.device_name}")
        lines.append(
            f"    desktop:    left={mon.left} top={mon.top} "
            f"width={mon.width} height={mon.height}"
        )
        lines.append(f"    dpi:        {dpi}")
        if mon.dxcam is not None:
            lines.append(
                f"    dxcam:      device_idx={mon.dxcam.device_idx} "
                f"output_idx={mon.dxcam.output_idx} "
                f"({mon.dxcam.device_name})"
            )
            if mon.dxcam.adapter_name:
                lines.append(f"    adapter:    {mon.dxcam.adapter_name}")
        else:
            lines.append("    dxcam:      (unmapped — capture may fail)")
        backend_bits = ", ".join(
            f"{name}={'yes' if ok else 'no'}"
            for name, ok in sorted(mon.backends_available.items())
        )
        lines.append(f"    backends:   {backend_bits}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
