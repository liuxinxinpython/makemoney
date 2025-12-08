from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView  # type: ignore[import-not-found]

try:
    import pandas as pd  # type: ignore[import-not-found]

    HAS_PANDAS = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_PANDAS = False
    pd = None  # type: ignore[assignment]

try:
    import akshare as ak  # type: ignore[import-not-found]

    HAS_AKSHARE = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_AKSHARE = False

try: 
    from src.data.import_excel_to_sqlite import import_directory
    HAS_IMPORTER = True
except Exception:  # pragma: no cover - optional dependency
    HAS_IMPORTER = False

try:
    from src.data.volume_price_selector import (
        PatternMatch,
        RangeSegment,
        ScanConfig,
        detect_pattern,
        load_price_frame,
        scan_database,
        segment_trend_and_consolidation,
    )
    HAS_SELECTOR = True
except Exception:  # pragma: no cover - optional dependency
    HAS_SELECTOR = False

# Workers and render helpers are moved to separate modules for modularity
try:
    from src.data.workers import ImportWorker, SymbolLoadWorker, CandleLoadWorker  # type: ignore[import-not-found]
except Exception:
    ImportWorker = None
    SymbolLoadWorker = None
    CandleLoadWorker = None

try:
    from src.rendering import render_html, build_mock_candles, load_maotai_candles  # type: ignore[import-not-found]
except Exception:
    render_html = None
    build_mock_candles = None
    load_maotai_candles = None

TEMPLATE_FILENAME = "tradingview_template.html"
TEMPLATE_PATH = Path(__file__).parent / "src" / "rendering" / "templates" / TEMPLATE_FILENAME
DEFAULT_DB_PATH = Path(__file__).parent / "src" / "data" / "a_share_daily.db"


try:
    from src.data.data_loader import load_candles_from_sqlite  # type: ignore[import-not-found]
except Exception:
    load_candles_from_sqlite = None

_THEME_IMPORT_ERROR: Optional[str] = None

try:
    from src.ui.theme import apply_app_theme  # type: ignore[import-not-found]
except Exception as exc:
    _THEME_IMPORT_ERROR = repr(exc)

    def apply_app_theme(app: QtWidgets.QApplication, *, source: Optional[str] = None) -> None:  # type: ignore[unused-argument]
        """Fallback no-op when theme module is unavailable."""
        origin = source or "unknown"
        print(f"[UI] Theme module import failed (source={origin}): {_THEME_IMPORT_ERROR}")
        return


class DebuggableWebEnginePage(QWebEnginePage):
    consoleMessage = QtCore.pyqtSignal(str)

    def javaScriptConsoleMessage(self, level: QWebEnginePage.JavaScriptConsoleMessageLevel, message: str, line_number: int, source_id: str) -> None:  # type: ignore[override]
        level_name = {
            QWebEnginePage.InfoMessageLevel: "INFO",
            QWebEnginePage.WarningMessageLevel: "WARN",
            QWebEnginePage.ErrorMessageLevel: "ERROR",
        }.get(level, "LOG")
        source = source_id.split("/")[-1] if source_id else ""
        formatted = f"JS[{level_name}] {message} (line {line_number}{', ' + source if source else ''})"
        self.consoleMessage.emit(formatted)
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


try:
    from src.main_ui import MainWindow  # type: ignore[import-not-found]
except Exception:
    # Fallback stub: if main_ui cannot be imported we provide a minimal MainWindow implementation
    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("A 股 K 线与导入工具（缺少 main_ui）")
            self.resize(800, 480)
            label = QtWidgets.QLabel("无法加载主界面模块 main_ui.py。请检查模块是否存在。", self)
            label.setWordWrap(True)
            self.setCentralWidget(label)


def main() -> None:
    import sys

    app = QtWidgets.QApplication(sys.argv)
    apply_app_theme(app, source="main.py")
    app.setProperty("snow_theme_applied", True)
    window = MainWindow(db_path=DEFAULT_DB_PATH)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
