from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]
from PyQt5.QtWebEngineWidgets import QWebEngineView  # type: ignore[import-not-found]


class EChartsPreviewDialog(QtWidgets.QDialog):
    """独立的 ECharts 预览窗口，用于并排查看策略结果。"""

    def __init__(self, template_path: Path, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ECharts 策略预览")
        self.resize(980, 640)
        self.setModal(False)
        self.setWindowFlags(
            self.windowFlags()
            | QtCore.Qt.Window
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowMaximizeButtonHint
            | QtCore.Qt.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self._template_path = template_path
        self._maximize_on_show = True

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.web_view = QWebEngineView(self)
        layout.addWidget(self.web_view, 1)

    def show_html(self, title: str, html: str) -> None:
        """渲染 HTML 并显示窗口。"""
        self.setWindowTitle(title)
        base_url = QtCore.QUrl.fromLocalFile(str(self._template_path))
        self.web_view.setHtml(html, base_url)
        self.show()
        if self._maximize_on_show:
            self.setWindowState(self.windowState() | QtCore.Qt.WindowMaximized)
            self._maximize_on_show = False
        self.raise_()
        self.activateWindow()


__all__ = ["EChartsPreviewDialog"]
