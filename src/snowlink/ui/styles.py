"""Application stylesheet — Material-inspired light blue / white / black text."""

from __future__ import annotations

APP_STYLESHEET = """
QWidget {
    background-color: #F7FBFF;
    color: #212121;
    font-family: "Segoe UI", "Roboto", sans-serif;
    font-size: 13px;
}
QMainWindow, QStackedWidget {
    background-color: #F7FBFF;
}
QLabel {
    background-color: transparent;
}
QWidget#navRail {
    background-color: #E3F2FD;
    border-right: 1px solid #BBDEFB;
}
QLabel#brandTitle {
    font-size: 18px;
    font-weight: 700;
    color: #1565C0;
    letter-spacing: 0.5px;
}
QLabel#brandWordmark {
    font-size: 13px;
    font-weight: 700;
    color: #1565C0;
}
QLabel#brandSubtitle {
    font-size: 11px;
    color: #546E7A;
}
QLabel#pageTitle {
    font-size: 15px;
    font-weight: 600;
    color: #212121;
}
QLabel#hint {
    color: #546E7A;
}
QLabel#warningBanner {
    background-color: #E3F2FD;
    color: #1565C0;
    padding: 6px 8px;
    border: 1px solid #BBDEFB;
    border-radius: 8px;
}
QLabel#pairingCode {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 3px;
    color: #2196F3;
}
QLabel#sharingIndicator {
    background-color: #FFEBEE;
    color: #C62828;
    padding: 8px 10px;
    border: 1px solid #EF9A9A;
    border-radius: 10px;
    font-weight: 600;
}
QLabel#statsPanel {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    color: #37474F;
    padding: 4px 2px;
}
QPushButton {
    background-color: #FFFFFF;
    color: #212121;
    border: 1px solid #BBDEFB;
    border-radius: 14px;
    padding: 4px 10px;
    min-height: 16px;
}
QPushButton:hover {
    background-color: #E3F2FD;
    border-color: #2196F3;
}
QPushButton:pressed {
    background-color: #BBDEFB;
}
QPushButton:disabled {
    background-color: #F5F5F5;
    color: #9E9E9E;
    border-color: #E0E0E0;
}
QPushButton#primaryButton {
    background-color: #2196F3;
    border-color: #2196F3;
    color: #FFFFFF;
    font-weight: 600;
    min-height: 18px;
    border-radius: 14px;
}
QPushButton#primaryButton:hover {
    background-color: #1E88E5;
    border-color: #1E88E5;
}
QPushButton#primaryButton:pressed {
    background-color: #1565C0;
    border-color: #1565C0;
}
QPushButton#primaryButton:disabled {
    background-color: #90CAF9;
    color: #FFFFFF;
    border-color: #90CAF9;
}
QPushButton#navButton {
    text-align: left;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 500;
    background-color: transparent;
    border: none;
    border-radius: 8px;
    color: #212121;
}
QPushButton#navButton:hover {
    background-color: #BBDEFB;
}
QPushButton#navButton[active="true"] {
    background-color: #FFFFFF;
    color: #1565C0;
    font-weight: 600;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {
    background-color: #FFFFFF;
    color: #212121;
    border: 1px solid #BBDEFB;
    border-radius: 10px;
    padding: 6px 10px;
    selection-background-color: #BBDEFB;
    selection-color: #1565C0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {
    border: 1px solid #2196F3;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #212121;
    selection-background-color: #E3F2FD;
    selection-color: #1565C0;
    border: 1px solid #BBDEFB;
}
QPlainTextEdit#logView {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}
QTabWidget::pane {
    border: 1px solid #BBDEFB;
    background: #FFFFFF;
    border-radius: 10px;
}
QTabBar::tab {
    background: #E3F2FD;
    color: #546E7A;
    padding: 8px 14px;
    border: 1px solid #BBDEFB;
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background: #2196F3;
    color: #FFFFFF;
}
QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #BBDEFB;
    border-radius: 12px;
    margin-top: 14px;
    padding-top: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #546E7A;
    font-weight: 600;
}
QCheckBox {
    color: #212121;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #2196F3;
    border-radius: 4px;
    background: #FFFFFF;
}
QCheckBox::indicator:hover {
    border: 2px solid #1565C0;
}
QCheckBox::indicator:checked {
    background: #2196F3;
    border: 2px solid #2196F3;
}
QGroupBox::indicator {
    width: 14px;
    height: 14px;
    border: 2px solid #2196F3;
    border-radius: 3px;
    background: #FFFFFF;
}
QGroupBox::indicator:checked {
    background: #2196F3;
    border: 2px solid #2196F3;
}
QStatusBar {
    background: #E3F2FD;
    color: #546E7A;
    border-top: 1px solid #BBDEFB;
}
QScrollBar:vertical {
    background: #F7FBFF;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #90CAF9;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QMessageBox {
    background-color: #FFFFFF;
}
"""
