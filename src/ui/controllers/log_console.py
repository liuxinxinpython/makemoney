from __future__ import annotations

from typing import List, Optional

from PyQt5 import QtCore, QtWidgets


class LogConsole(QtCore.QObject):
    """管理日志历史及弹窗。"""

    def __init__(
        self,
        *,
        parent: QtWidgets.QWidget,
        title: str = "导入日志",
        max_entries: int = 2000,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._title = title
        self._max_entries = max_entries
        self._history: List[str] = []
        self._dialog: Optional[QtWidgets.QDialog] = None
        self._text_edit: Optional[QtWidgets.QTextEdit] = None

    # ------------------------------------------------------------------
    def append(self, entry: str, *, force_show: bool = False) -> None:
        self._history.append(entry)
        if len(self._history) > self._max_entries:
            self._history = self._history[-self._max_entries :]

        if force_show:
            self.ensure(show=True)
        elif self._dialog is not None:
            self.ensure(show=False)

        if self._text_edit:
            self._text_edit.append(entry)

    def reset(self) -> None:
        self._history.clear()
        if self._text_edit:
            self._text_edit.clear()

    def ensure(self, *, show: bool = False) -> None:
        if self._dialog is None:
            self._dialog = QtWidgets.QDialog(self._parent)
            self._dialog.setWindowTitle(self._title)
            self._dialog.setModal(False)
            self._dialog.resize(520, 360)
            layout = QtWidgets.QVBoxLayout(self._dialog)
            text_edit = QtWidgets.QTextEdit(self._dialog)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, self._dialog)
            button_box.rejected.connect(self._dialog.reject)
            layout.addWidget(button_box)
            self._dialog.finished.connect(self._on_dialog_closed)
            self._text_edit = text_edit
            if self._history:
                for entry in self._history:
                    text_edit.append(entry)
        elif self._text_edit and not self._text_edit.toPlainText() and self._history:
            for entry in self._history:
                self._text_edit.append(entry)

        if show and self._dialog:
            self._dialog.show()
            self._dialog.raise_()
            self._dialog.activateWindow()

    # ------------------------------------------------------------------
    def _on_dialog_closed(self, _result: int) -> None:
        self._dialog = None
        self._text_edit = None
