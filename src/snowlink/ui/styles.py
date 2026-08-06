"""Application stylesheet — restrained slate / teal, not purple-on-white."""

from __future__ import annotations

APP_STYLESHEET = """
QWidget {
    background-color: #1a222c;
    color: #e8eef4;
    font-family: "Segoe UI", "Candara", sans-serif;
    font-size: 13px;
}
QMainWindow, QStackedWidget {
    background-color: #1a222c;
}
QLabel#brandTitle {
    font-size: 36px;
    font-weight: 700;
    color: #f2f7fb;
    letter-spacing: 1px;
}
QLabel#brandSubtitle {
    font-size: 14px;
    color: #9eb0c0;
}
QLabel#pageTitle {
    font-size: 22px;
    font-weight: 600;
    color: #f2f7fb;
}
QLabel#hint {
    color: #9eb0c0;
}
QLabel#warningBanner {
    background-color: #3a2f1a;
    color: #f0d9a0;
    padding: 10px 12px;
    border: 1px solid #6a5530;
    border-radius: 4px;
}
QPushButton {
    background-color: #2b3848;
    color: #e8eef4;
    border: 1px solid #3d4f63;
    border-radius: 4px;
    padding: 8px 14px;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #35485c;
}
QPushButton:pressed {
    background-color: #243040;
}
QPushButton#primaryButton {
    background-color: #1f6f6a;
    border-color: #2a8f88;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #258882;
}
QPushButton#primaryButton:disabled {
    background-color: #3a454d;
    color: #8a969f;
    border-color: #4a5560;
}
QPushButton#navButton {
    text-align: left;
    padding: 14px 18px;
    font-size: 15px;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {
    background-color: #121820;
    color: #e8eef4;
    border: 1px solid #3d4f63;
    border-radius: 4px;
    padding: 6px 8px;
    selection-background-color: #1f6f6a;
}
QPlainTextEdit#logView {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}
QTabWidget::pane {
    border: 1px solid #3d4f63;
    background: #1a222c;
}
QTabBar::tab {
    background: #243040;
    color: #c5d2de;
    padding: 8px 14px;
    border: 1px solid #3d4f63;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #1f6f6a;
    color: #ffffff;
}
QGroupBox {
    border: 1px solid #3d4f63;
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #9eb0c0;
}
QStatusBar {
    background: #121820;
    color: #9eb0c0;
}
"""
