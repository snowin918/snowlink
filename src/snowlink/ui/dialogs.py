"""Modal dialogs for the Snowlink shell."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox, QWidget


def prompt_incoming_connection(
    parent: QWidget | None,
    info: Any,
) -> bool:
    """AnyDesk-style Accept / Deny modal for an incoming viewer.

    Returns True if the user accepts.
    """
    remote = getattr(info, "remote_addr", None) or "?"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Incoming connection")
    box.setText("Someone wants to view this computer.")
    box.setInformativeText(
        f"Viewer address: {remote}\n\n"
        "Accept only if you started this connection on your other PC."
    )
    accept_btn = box.addButton("Accept", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Deny", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(accept_btn)
    box.exec()
    return box.clickedButton() is accept_btn
