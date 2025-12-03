from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView  # type: ignore[import-not-found]

try:
    from .data.volume_price_selector import (
        PatternMatch,
        RangeSegment,
        ScanConfig,
        detect_pattern,
        load_price_frame,
        scan_database,
        segment_trend_and_consolidation,
    )
    HAS_SELECTOR = True
except Exception:
    HAS_SELECTOR = False
    PatternMatch = object
    RangeSegment = object
    ScanConfig = object
    detect_pattern = None
    load_price_frame = None
    scan_database = None
    segment_trend_and_consolidation = None

try:
    from .data.workers import ImportWorker  # type: ignore[import-not-found]
except Exception:
    ImportWorker = None

try:
    from .displays import DisplayManager
except Exception:
    DisplayManager = None

try:
    from .ui import KLineController, StrategyWorkbenchController
except Exception:
    KLineController = None
    StrategyWorkbenchController = None


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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, db_path: Optional[Path] = None) -> None:
        super().__init__()
        self.setWindowTitle("A股K线与导入工具")
        self.resize(1200, 720)

        # The MainWindow code below is copied from tradingview_kline.py

        self.data_dir: Optional[Path] = None
        self.db_path: Path = db_path or Path("a_share_daily.db")
        self.import_thread: Optional[QtCore.QThread] = None
        self.import_worker: Optional[QtCore.QObject] = None

        self.web_page = DebuggableWebEnginePage(self)
        self.web_page.consoleMessage.connect(self._on_js_console_message)
        self.web_view = QWebEngineView(self)
        self.web_view.setPage(self.web_page)
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 添加顶部进度条
        self.loading_progress = QtWidgets.QProgressBar(self)
        self.loading_progress.setVisible(False)
        self.loading_progress.setRange(0, 0)  # 不确定进度模式
        self.loading_progress.setFixedHeight(3)  # 更细的进度条
        self.loading_progress.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: rgba(240, 240, 240, 0.8);
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0078d4,
                    stop:1 #005a9e);
                border-radius: 1px;
            }
        """)
        layout.addWidget(self.loading_progress)
        
        layout.addWidget(self.web_view)
        self.setCentralWidget(container)

        self.symbol_combo = QtWidgets.QComboBox(self)
        self.symbol_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)

        self.symbol_search = QtWidgets.QLineEdit(self)
        self.symbol_search.setPlaceholderText("输入代码或名称搜索")
        self.symbol_search.setClearButtonEnabled(True)

        self.log_dialog: Optional[QtWidgets.QDialog] = None
        self.log_text: Optional[QtWidgets.QTextEdit] = None
        self.log_history: List[str] = []
        self.kline_controller: Optional[KLineController] = None
        self.workbench_controller: Optional[StrategyWorkbenchController] = None
        self.strategy_button: Optional[QtWidgets.QToolButton] = None

        # Initialize display manager
        self.display_manager = DisplayManager() if DisplayManager else None

        # Register chart display if available
        if self.display_manager and hasattr(self, 'web_view'):
            try:
                from displays.chart_display import ChartDisplay
                chart_display = ChartDisplay(self)
                self.display_manager.register_display("chart", chart_display)
            except Exception:
                pass

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._init_kline_controller()
        self._init_workbench_controller()

        self.statusBar().showMessage("就绪")
        # 导入进度条(用于导入过程的可视反馈)
        self.import_progress = QtWidgets.QProgressBar(self)
        self.import_progress.setVisible(False)
        self.import_progress.setFixedWidth(150)
        self.statusBar().addPermanentWidget(self.import_progress)
        if self.kline_controller:
            self.kline_controller.load_initial_chart()

    # Insert MainWindow methods (copied from tradingview_kline.py)
    def _create_actions(self) -> None:
        self.action_choose_dir = QtWidgets.QAction("选择数据目录...", self)
        self.action_choose_dir.triggered.connect(self.choose_data_directory)

        self.action_choose_db = QtWidgets.QAction("选择数据库文件...", self)
        self.action_choose_db.triggered.connect(self.choose_database_file)

        # 保留原有的单次导入操作作为通用入口(由参数决定追加或重建)
        self.action_import = QtWidgets.QAction("导入到 SQLite", self)
        self.action_import.triggered.connect(self.start_import)
        self.action_import.setEnabled(False)

        self.action_refresh_symbols = QtWidgets.QAction("刷新标的列表", self)
        self.action_refresh_symbols.triggered.connect(self.refresh_symbols)

        # 设置图标和工具提示,提升可用性
        style = QtWidgets.QApplication.style()
        try:
            self.action_choose_dir.setIcon(style.standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
            self.action_choose_db.setIcon(style.standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))
            self.action_import.setIcon(style.standardIcon(QtWidgets.QStyle.SP_BrowserReload))
            self.action_refresh_symbols.setIcon(style.standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        except Exception:
            pass
        self.action_choose_dir.setToolTip("选择本地数据目录(Excel/CSV)并导入至数据库")
        self.action_choose_db.setToolTip("选择或创建 SQLite 数据库文件用于保存行情 K 线")
        self.action_import.setToolTip("导入本地数据到 SQLite(默认追加,可在导入菜单中选择重建)")
        self.action_refresh_symbols.setToolTip("刷新数据库中的标的列表")

    def _create_menus(self) -> None:
        menu_data = self.menuBar().addMenu("数据")
        menu_data.addAction(self.action_choose_dir)
        menu_data.addAction(self.action_choose_db)
        menu_data.addSeparator()
        # 导入子菜单,提供"追加导入 / 重建导入"选项
        self.import_menu = QtWidgets.QMenu("导入", self)
        self.action_import_append = QtWidgets.QAction("导入(追加)", self)
        self.action_import_append.triggered.connect(lambda: self.start_import(False))
        self.action_import_replace = QtWidgets.QAction("导入(重建)", self)
        self.action_import_replace.triggered.connect(lambda: self.start_import(True))
        self.action_import_append.setToolTip("将新数据追加到现有数据表中(非破坏性)")
        self.action_import_replace.setToolTip("删除并重建目标数据表,以新数据覆盖现有记录")
        try:
            style2 = QtWidgets.QApplication.style()
            self.action_import_append.setIcon(style2.standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
            self.action_import_replace.setIcon(style2.standardIcon(QtWidgets.QStyle.SP_TrashIcon))
        except Exception:
            pass
        self.import_menu.addAction(self.action_import_append)
        self.import_menu.addAction(self.action_import_replace)
        menu_data.addMenu(self.import_menu)
        menu_data.addAction(self.action_refresh_symbols)

    def _create_toolbar(self) -> None:
        toolbar = self.addToolBar("导入")
        toolbar.setMovable(False)
        # 左侧:数据操作
        toolbar.addAction(self.action_choose_dir)
        # 使用一个工具按钮承载导入子菜单
        import_toolbtn = QtWidgets.QToolButton(self)
        import_toolbtn.setText("导入")
        import_toolbtn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        import_toolbtn.setMenu(self.import_menu)
        import_toolbtn.setToolTip("将本地数据导入数据库(可选择追加或重建)")
        try:
            import_toolbtn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        except Exception:
            pass
        toolbar.addWidget(import_toolbtn)
        toolbar.addSeparator()

        toolbar.addWidget(QtWidgets.QLabel("当前数据库:", self))
        self.db_path_label = QtWidgets.QLabel(str(self.db_path.resolve()), self)
        toolbar.addWidget(self.db_path_label)
        toolbar.addSeparator()

        toolbar.addWidget(QtWidgets.QLabel("标的:", self))
        toolbar.addWidget(self.symbol_combo)
        toolbar.addSeparator()
        # 移除工具栏上的重建导入复选框,改由导入菜单控制
        toolbar.addWidget(QtWidgets.QLabel("搜索:", self))
        self.symbol_search.setMaximumWidth(220)
        toolbar.addWidget(self.symbol_search)
        toolbar.addSeparator()
        self.strategy_button = QtWidgets.QToolButton(self)
        self.strategy_button.setText("策略选股")
        self.strategy_button.setToolTip("打开策略工作台")
        self.strategy_button.clicked.connect(self._show_strategy_workbench)
        toolbar.addWidget(self.strategy_button)
        toolbar.addSeparator()

    def _init_kline_controller(self) -> None:
        if KLineController is None:
            self.append_log("KLine 控制器不可用，图表无法模块化管理。")
            return
        self.kline_controller = KLineController(
            web_view=self.web_view,
            loading_progress=self.loading_progress,
            status_bar=self.statusBar(),
            symbol_combo=self.symbol_combo,
            symbol_search=self.symbol_search,
            db_path_getter=lambda: self.db_path,
            log_handler=self.append_log,
            display_manager=self.display_manager,
            parent=self,
        )

    def _init_workbench_controller(self) -> None:
        if StrategyWorkbenchController is None or self.kline_controller is None:
            return

        controller = StrategyWorkbenchController(
            parent_window=self,
            status_bar=self.statusBar(),
            kline_controller=self.kline_controller,
            db_path_getter=lambda: self.db_path,
            log_handler=self.append_log,
            parent=self,
        )
        controller.initialize()
        self.workbench_controller = controller

    def _show_strategy_workbench(self) -> None:
        if self.workbench_controller is None:
            self._init_workbench_controller()
        if self.workbench_controller:
            self.workbench_controller.toggle_visibility(True)

    def _ensure_log_dialog(self, *, show: bool = False) -> None:
        if self.log_dialog is None:
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("导入日志")
            dialog.setModal(False)
            dialog.resize(520, 360)

            layout = QtWidgets.QVBoxLayout(dialog)
            text_edit = QtWidgets.QTextEdit(dialog)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)

            button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, dialog)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)

            dialog.finished.connect(self._on_log_dialog_closed)

            self.log_dialog = dialog
            self.log_text = text_edit
            if self.log_history:
                for entry in self.log_history:
                    text_edit.append(entry)
        elif self.log_text and not self.log_text.toPlainText() and self.log_history:
            for entry in self.log_history:
                self.log_text.append(entry)

        if show and self.log_dialog:
            self.log_dialog.show()
            self.log_dialog.raise_()
            self.log_dialog.activateWindow()

    def _on_log_dialog_closed(self, _result: int) -> None:
        self.log_dialog = None
        self.log_text = None

    def append_log(self, message: str, *, force_show: bool = False) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.log_history.append(entry)
        if len(self.log_history) > 2000:
            self.log_history = self.log_history[-2000:]

        if force_show:
            self._ensure_log_dialog(show=True)
        elif self.log_dialog is not None:
            self._ensure_log_dialog(show=False)

        if self.log_text:
            self.log_text.append(entry)

    def _on_js_console_message(self, message: str) -> None:
        self.append_log(f"[JS] {message}")

    def choose_data_directory(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "选择包含 Excel/CSV 的目录")
        if not directory:
            return

        self.data_dir = Path(directory)
        self.append_log(f"已选择数据目录: {self.data_dir}")
        self.statusBar().showMessage(f"数据目录: {self.data_dir}")
        self.action_import.setEnabled(True)
        self.action_import_append.setEnabled(True)
        self.action_import_replace.setEnabled(True)

    def choose_database_file(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "选择或创建 SQLite 数据库",
            str(self.db_path.resolve()),
            "SQLite 数据库 (*.db);;所有文件 (*.*)",
        )
        if not file_path:
            return

        self.db_path = Path(file_path)
        display_path = str(self.db_path.resolve())
        self.db_path_label.setText(display_path)
        self.db_path_label.setToolTip(display_path)
        self.append_log(f"数据库路径已更新为: {self.db_path}")
        # Refresh symbols asynchronously to avoid blocking UI when DB is large.
        self.refresh_symbols_async()

    def start_import(self, replace: Optional[bool] = None) -> None:
        if self.data_dir is None:
            QtWidgets.QMessageBox.warning(self, "缺少目录", "请先选择包含 Excel/CSV 的数据目录。")
            return

        if self.import_thread is not None:
            QtWidgets.QMessageBox.information(self, "导入进行中", "导入任务正在执行，请稍候。")
            return

        self.log_history.clear()
        if self.log_text:
            self.log_text.clear()
        self._ensure_log_dialog(show=True)

        replace_mode = bool(replace) if replace is not None else False
        if replace_mode:
            confirm = QtWidgets.QMessageBox.question(
                self,
                "确认重建导入",
                "重建导入会清空数据库中的目标表并用新数据覆盖，是否继续？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if confirm != QtWidgets.QMessageBox.Yes:
                self.append_log("用户取消了重建导入。")
                return
        self.append_log("准备导入数据...", force_show=True)
        self.append_log(f"导入模式: {'重建' if replace_mode else '追加'}")

        self.import_worker = ImportWorker(self.data_dir, self.db_path, replace=replace_mode)
        self.import_thread = QtCore.QThread(self)
        self.import_worker.moveToThread(self.import_thread)

        self.import_thread.started.connect(self.import_worker.run)
        self.import_worker.progress.connect(self.append_log)
        self.import_worker.finished.connect(self.on_import_finished)
        self.import_worker.failed.connect(self.on_import_failed)
        self.import_worker.finished.connect(self.import_thread.quit)
        self.import_worker.failed.connect(self.import_thread.quit)
        self.import_thread.finished.connect(self.cleanup_import_thread)

        self.action_import.setEnabled(False)
        self.action_import_append.setEnabled(False)
        self.action_import_replace.setEnabled(False)
        self.action_choose_dir.setEnabled(False)
        self.statusBar().showMessage("正在导入...")

        # 显示进度条（不确定模式，直到完成）
        self.import_progress.setVisible(True)
        self.import_progress.setRange(0, 0)
        self.import_thread.start()

    def cleanup_import_thread(self) -> None:
        if self.import_worker is not None:
            self.import_worker.deleteLater()
            self.import_worker = None
        if self.import_thread is not None:
            self.import_thread.deleteLater()
            self.import_thread = None

        self.action_import.setEnabled(self.data_dir is not None)
        self.action_import_append.setEnabled(self.data_dir is not None)
        self.action_import_replace.setEnabled(self.data_dir is not None)
        self.action_choose_dir.setEnabled(True)
        # 隐藏进度条
        try:
            self.import_progress.setVisible(False)
        except Exception:
            pass

    def on_import_finished(self, tables: List[str]) -> None:
        self.append_log("导入任务完成。")
        self.statusBar().showMessage("导入完成")
        try:
            self.import_progress.setVisible(False)
        except Exception:
            pass
        self.refresh_symbols_async(select=tables[0] if tables else None)

    def on_import_failed(self, error_message: str) -> None:
        self.append_log(f"导入失败: {error_message}")
        QtWidgets.QMessageBox.critical(self, "导入失败", error_message)
        self.statusBar().showMessage("导入失败")
        try:
            self.import_progress.setVisible(False)
        except Exception:
            pass

    def refresh_symbols(self, select: Optional[str] = None) -> List[str]:
        if self.kline_controller:
            return self.kline_controller.refresh_symbols(select)
        return []

    def refresh_symbols_async(self, select: Optional[str] = None) -> None:
        if self.kline_controller:
            self.kline_controller.refresh_symbols_async(select)
# End of main_ui.py
