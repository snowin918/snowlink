"""Aspect-ratio-preserving frame scaling (CPU / OpenCV).

Policy: *fit inside* the requested output box while preserving aspect ratio,
then letterbox with black bars so the final image is exactly WxH. Never stretch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from snowlink.media.capture_errors import CaptureError, failure_for


@dataclass(frozen=True, slots=True)
class LetterboxGeometry:
    """Geometry for fitting *src* into *dst* with letterboxing."""

    content_width: int
    content_height: int
    pad_left: int
    pad_top: int
    pad_right: int
    pad_bottom: int
    output_width: int
    output_height: int


def compute_letterbox_geometry(
    src_width: int,
    src_height: int,
    dst_width: int,
    dst_height: int,
) -> LetterboxGeometry:
    """Compute fit-inside letterbox geometry (no stretching)."""
    if src_width <= 0 or src_height <= 0 or dst_width <= 0 or dst_height <= 0:
        raise CaptureError(
            failure_for(
                "SCALING_FAILED",
                "Source and destination dimensions must be positive.",
            )
        )
    scale = min(dst_width / src_width, dst_height / src_height)
    content_w = max(1, int(round(src_width * scale)))
    content_h = max(1, int(round(src_height * scale)))
    # Clamp if rounding overflowed the box.
    content_w = min(content_w, dst_width)
    content_h = min(content_h, dst_height)
    pad_x = dst_width - content_w
    pad_y = dst_height - content_h
    pad_left = pad_x // 2
    pad_top = pad_y // 2
    pad_right = pad_x - pad_left
    pad_bottom = pad_y - pad_top
    return LetterboxGeometry(
        content_width=content_w,
        content_height=content_h,
        pad_left=pad_left,
        pad_top=pad_top,
        pad_right=pad_right,
        pad_bottom=pad_bottom,
        output_width=dst_width,
        output_height=dst_height,
    )


def scale_frame_letterbox(
    frame: Any,
    dst_width: int,
    dst_height: int,
    *,
    cv2_module: Any | None = None,
) -> Any:
    """Scale *frame* to *dst_width* x *dst_height* with letterboxing.

    Uses OpenCV ``cv2.resize`` + ``cv2.copyMakeBorder``. The final array shape is
    exactly ``(dst_height, dst_width, channels)``.
    """
    if frame is None:
        raise CaptureError(
            failure_for("SCALING_FAILED", "Cannot scale a null frame.")
        )
    try:
        src_h, src_w = int(frame.shape[0]), int(frame.shape[1])
    except Exception as exc:
        raise CaptureError(
            failure_for(
                "SCALING_FAILED",
                "Frame does not have a usable HxW shape.",
                exception=exc,
            )
        ) from exc

    if src_w == dst_width and src_h == dst_height:
        return frame

    geom = compute_letterbox_geometry(src_w, src_h, dst_width, dst_height)
    cv2 = cv2_module
    if cv2 is None:
        try:
            import cv2 as cv2_imported
        except ModuleNotFoundError as exc:
            raise CaptureError(
                failure_for(
                    "SCALING_FAILED",
                    "OpenCV (cv2) is required for frame scaling.",
                    exception=exc,
                )
            ) from exc
        cv2 = cv2_imported

    try:
        resized = cv2.resize(
            frame,
            (geom.content_width, geom.content_height),
            interpolation=cv2.INTER_AREA,
        )
        return cv2.copyMakeBorder(
            resized,
            geom.pad_top,
            geom.pad_bottom,
            geom.pad_left,
            geom.pad_right,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )
    except Exception as exc:
        raise CaptureError(
            failure_for(
                "SCALING_FAILED",
                "OpenCV failed while scaling/letterboxing the frame.",
                exception=exc,
            )
        ) from exc
