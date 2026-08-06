"""Confirm the snowlink package imports successfully."""

from __future__ import annotations


def test_snowlink_package_imports() -> None:
    import snowlink

    assert snowlink.__version__ == "0.1.0"
