from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5 import QtWidgets  # type: ignore[import-not-found]

_LIGHT_STYLE = r"""
/* SnowYing desktop-inspired palette */
* {
    color: #1b2236;
    font-family: 'Segoe UI', 'Source Han Sans SC', 'Microsoft YaHei', 'PingFang SC', system-ui;
    font-size: 13px;
    letter-spacing: 0.15px;
}

QMainWindow,
QWidget#StrategyWorkbench,
QDialog {
    background-color: #f4f6fb;
}

QFrame,
QGroupBox {
    background-color: #ffffff;
    border: none;
    border-radius: 0;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    top: 10px;
    color: #1f5eff;
    font-weight: 600;
}

#WorkbenchTitle {
    font-size: 19px;
    font-weight: 600;
    color: #121833;
    padding-left: 4px;
}

#StrategyCardPanel,
#StrategyDetailPanel,
#StrategyWorkbenchTabs,
#StrategyDetailPanel QWidget {
    border-radius: 0;
}

#StrategyDetailPanel {
    padding: 12px 14px 16px;
}

#StrategyDescription {
    color: #56617f;
    line-height: 1.45;
}

#KpiStrip {
    background: transparent;
    border: none;
}

#KpiCard {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
}

#KpiTitle {
    color: #6a7696;
    font-size: 12px;
    letter-spacing: 0.4px;
}

#KpiValue {
    font-size: 28px;
    font-weight: 600;
    color: #111b3d;
}

QTabWidget::pane {
    border: none;
    border-radius: 0;
    background: #f9faff;
    padding: 10px;
}

QTabWidget::tab-bar {
    left: 6px;
}

QTabBar::tab {
    background: #edf1fb;
    border-radius: 16px;
    border: 1px solid transparent;
    padding: 6px 22px;
    margin: 0 4px;
    color: #5c688e;
    min-height: 32px;
}

QTabBar::tab:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5a9dff,
        stop:1 #2470ff);
    color: #ffffff;
    border: none;
    font-weight: 600;
}

QLineEdit,
QComboBox,
QDateEdit,
QSpinBox,
QDoubleSpinBox {
    background: #f8faff;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 6px 12px;
}

QLineEdit:focus,
QComboBox:focus,
QDateEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: #1f5eff;
    background: #ffffff;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    selection-background-color: #e1ecff;
    selection-color: #123463;
    border: 1px solid #c2d2f3;
}

QPushButton {
    border-radius: 10px;
    padding: 6px 18px;
    font-weight: 600;
    border: none;
    background: #f3f5fb;
    color: #1c243b;
    min-height: 32px;
}

QPushButton:hover {
    background: #e8ecf7;
}

QPushButton[class~="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5fa6ff,
        stop:1 #1f6dff);
    color: #ffffff;
    border: none;
}

QPushButton[class~="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6ab1ff,
        stop:1 #387dff);
}

QPushButton[class~="ghost"] {
    background: #eef2fb;
    border: none;
    color: #1b2236;
}

QPushButton[class~="danger"] {
    background: #fff1e9;
    border: none;
    color: #c45525;
}

QPushButton:disabled {
    background: #eceff6;
    color: rgba(69, 80, 108, 0.55);
    border-color: transparent;
}

QScrollBar:vertical,
QScrollBar:horizontal {
    background: transparent;
    border: none;
    width: 10px;
    margin: 10px 0;
}

QScrollBar::handle {
    background: rgba(111, 139, 196, 0.55);
    border-radius: 5px;
}

QSplitter::handle {
    background: #dfe5f2;
}

QListWidget#StrategyCardList {
    background: transparent;
    border: none;
}

QListWidget#StrategyCardList::item {
    background: #ffffff;
    border: none;
    border-radius: 0;
    margin: 4px 2px;
    padding: 8px 10px;
}

QListWidget#StrategyCardList::item:hover {
    border: none;
    background: rgba(229, 236, 255, 0.6);
}

QListWidget#StrategyCardList::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #f7f9ff,
        stop:1 #e1eaff);
    color: #1b2236;
}

QTableWidget[class~="data-table"] {
    background: #ffffff;
    border: none;
    border-radius: 0;
    gridline-color: rgba(142, 155, 186, 0.35);
}

QHeaderView::section {
    background: #f5f7fd;
    border: none;
    padding: 8px;
    font-weight: 600;
    color: #525f82;
}

QTableWidget::item:selected {
    background: rgba(39, 110, 255, 0.15);
    color: #111b3d;
}

QTextEdit#LogPanel {
    background: #ffffff;
    border: none;
    border-radius: 0;
    padding: 12px;
}

QToolBar {
    background: #ffffff;
    border: none;
    border-radius: 0;
    padding: 6px 10px;
    spacing: 8px;
}

QToolBar QWidget {
    color: #1b2236;
}
"""


def _log_theme_event(message: str) -> None:
    try:
        log_path = Path(__file__).resolve().parents[1] / "theme_debug.log"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def apply_app_theme(app: QtWidgets.QApplication, *, source: Optional[str] = None) -> None:
    """Apply the SnowYing desktop-inspired light theme."""
    app.setStyleSheet(_LIGHT_STYLE)
    app.setProperty("snow_theme_version", "snowying-desktop-2025.12")
    origin = source or "unknown"
    msg = f"Applied SnowYing desktop theme (source={origin}, app_id={id(app)})"
    print(f"[UI] {msg}")
    _log_theme_event(msg)


__all__ = ["apply_app_theme"]
