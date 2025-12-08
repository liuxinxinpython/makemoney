from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PyQt5 import QtCore, QtWidgets


class ImportController(QtCore.QObject):
    """封装导入线程及 UI 状态切换。"""

    def __init__(
        self,
        *,
        parent: QtWidgets.QWidget,
        data_dir_getter: Callable[[], Optional[Path]],
        db_path_getter: Callable[[], Path],
        import_worker_cls,
        log_handler: Callable[[str], None],
        log_reset: Callable[[], None],
        ensure_log_dialog: Callable[[bool], None],
        status_setter: Callable[[str], None],
        status_bar: QtWidgets.QStatusBar,
        import_progress: QtWidgets.QProgressBar,
        data_progress_getter: Callable[[], Optional[QtWidgets.QProgressBar]],
        refresh_symbols_async: Callable[[Optional[str]], None],
        action_choose_dir: QtWidgets.QAction,
        action_import_append: QtWidgets.QAction,
        action_import_replace: QtWidgets.QAction,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._data_dir_getter = data_dir_getter
        self._db_path_getter = db_path_getter
        self._worker_cls = import_worker_cls
        self._log = log_handler
        self._log_reset = log_reset
        self._ensure_log_dialog = ensure_log_dialog
        self._status_setter = status_setter
        self._status_bar = status_bar
        self._import_progress = import_progress
        self._data_progress_getter = data_progress_getter
        self._refresh_symbols_async = refresh_symbols_async
        self._action_choose_dir = action_choose_dir
        self._action_import_append = action_import_append
        self._action_import_replace = action_import_replace
        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[QtCore.QObject] = None

    # ------------------------------------------------------------------
    def start_import(self, replace: Optional[bool] = None) -> None:
        data_dir = self._data_dir_getter()
        if data_dir is None:
            QtWidgets.QMessageBox.warning(self._parent, "缺少目录", "请先选择包含 Excel/CSV 的数据目录。")
            return
        if self._thread is not None:
            QtWidgets.QMessageBox.information(self._parent, "导入进行中", "导入任务正在执行，请稍候。")
            return
        if self._worker_cls is None:
            QtWidgets.QMessageBox.warning(self._parent, "导入模块缺失", "当前环境缺少 ImportWorker，无法执行导入。")
            return

        self._log_reset()
        self._ensure_log_dialog(show=True)

        replace_mode = bool(replace) if replace is not None else False
        if replace_mode and not self._confirm_replace():
            self._log("用户取消了重建导入。")
            return

        self._log("准备导入数据...", force_show=True)
        self._log(f"导入模式: {'重建' if replace_mode else '追加'}")
        self._status_setter("正在导入...")
        self._set_data_progress(indeterminate=True)

        self._worker = self._worker_cls(data_dir, self._db_path_getter(), replace=replace_mode)
        self._thread = QtCore.QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)  # type: ignore[attr-defined]
        self._worker.progress.connect(self._log)
        self._worker.finished.connect(self._handle_finished)
        self._worker.failed.connect(self._handle_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)

        self._set_actions_enabled(False)
        self._status_bar.showMessage("正在导入...")
        self._import_progress.setVisible(True)
        self._import_progress.setRange(0, 0)
        self._thread.start()

    # ------------------------------------------------------------------
    def _confirm_replace(self) -> bool:
        confirm = QtWidgets.QMessageBox.question(
            self._parent,
            "确认重建导入",
            "重建导入会清空数据库中的目标表并用新数据覆盖，是否继续？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return confirm == QtWidgets.QMessageBox.Yes

    def _handle_finished(self, tables: List[str]) -> None:
        self._log("导入任务完成。")
        self._status_bar.showMessage("导入完成")
        self._status_setter("导入完成")
        self._import_progress.setVisible(False)
        self._set_data_progress(indeterminate=False, visible=False)
        select_table = tables[0] if tables else None
        self._refresh_symbols_async(select=select_table)

    def _handle_failed(self, error_message: str) -> None:
        self._log(f"导入失败: {error_message}")
        QtWidgets.QMessageBox.critical(self._parent, "导入失败", error_message)
        self._status_bar.showMessage("导入失败")
        self._status_setter("导入失败")
        self._import_progress.setVisible(False)
        self._set_data_progress(indeterminate=False, visible=False)

    def _cleanup_thread(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        has_data_dir = self._data_dir_getter() is not None
        self._action_import_append.setEnabled(has_data_dir)
        self._action_import_replace.setEnabled(has_data_dir)
        self._action_choose_dir.setEnabled(True)
        self._import_progress.setVisible(False)
        self._set_data_progress(indeterminate=False, visible=False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._action_choose_dir.setEnabled(enabled)
        self._action_import_append.setEnabled(enabled)
        self._action_import_replace.setEnabled(enabled)

    def _set_data_progress(self, *, indeterminate: bool, visible: bool = True) -> None:
        progress = self._data_progress_getter()
        if progress is None:
            return
        progress.setVisible(visible)
        progress.setRange(0, 0 if indeterminate else 1)