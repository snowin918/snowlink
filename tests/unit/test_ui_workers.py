"""Focused tests for Qt worker frame conversion."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")


def test_bgra_to_qimage_discards_alpha_without_corrupting_row_stride() -> None:
    from snowlink.ui.workers import _bgr_to_qimage

    bgra = np.array(
        [
            [[1, 2, 3, 40], [4, 5, 6, 50], [7, 8, 9, 60]],
            [[11, 12, 13, 70], [14, 15, 16, 80], [17, 18, 19, 90]],
        ],
        dtype=np.uint8,
    )

    image = _bgr_to_qimage(bgra)

    assert image is not None
    assert (image.width(), image.height()) == (3, 2)
    expected = [
        (3, 2, 1),
        (6, 5, 4),
        (9, 8, 7),
        (13, 12, 11),
        (16, 15, 14),
        (19, 18, 17),
    ]
    actual = [
        tuple(image.pixelColor(x, y).getRgb()[:3])
        for y in range(image.height())
        for x in range(image.width())
    ]
    assert actual == expected
