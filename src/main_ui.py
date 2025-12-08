from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView  # type: ignore[import-not-found]

from .ui.controllers import ImportController, LogConsole, StrategyPanelController, SymbolListManager
from .ui.data import load_sample_symbols
from .ui.pages import SnowDataPage, SnowQuotesPage
from .ui.widgets.left_nav import SnowLeftNav
from .ui.widgets.top_header import SnowTopHeader

try:
    from .ui.theme import apply_app_theme  # type: ignore[import-not-found]
except Exception as exc:
    print(f"[UI] Failed to import theme inside main_ui: {exc}")
    apply_app_theme = None

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

if TYPE_CHECKING:  # pragma: no cover
    from .ui import KLineController as KLineControllerType
    from .ui import StrategyWorkbenchController as StrategyWorkbenchControllerType
else:  # Fallback to object for runtime annotation safety
    KLineControllerType = object
    StrategyWorkbenchControllerType = object

try:
    from .rendering import render_echarts_demo, ECHARTS_TEMPLATE_PATH  # type: ignore[import-not-found]
except Exception:
    render_echarts_demo = None
    ECHARTS_TEMPLATE_PATH = Path(__file__).parent / "rendering" / "templates" / "echarts_demo.html"


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
        app = QtWidgets.QApplication.instance()
        if app and callable(apply_app_theme) and not app.property("snow_theme_applied"):
            apply_app_theme(app, source="main_ui.py")
            app.setProperty("snow_theme_applied", True)
        self.setWindowTitle("A股K线与导入工具")
        self.resize(1200, 720)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)

        # The MainWindow code below is copied from tradingview_kline.py

        self.data_dir: Optional[Path] = None
        self.db_path: Path = db_path or Path("a_share_daily.db")
        self.import_controller: Optional[ImportController] = None

        self.web_page = DebuggableWebEnginePage(self)
        self.web_page.consoleMessage.connect(self._on_js_console_message)
        self.web_view = QWebEngineView(self)
        self.web_view.setPage(self.web_page)

        # 顶部进度条在新的雪盈布局里嵌入主内容区域
        self.loading_progress = QtWidgets.QProgressBar(self)
        self.loading_progress.setVisible(False)
        self.loading_progress.setRange(0, 0)  # 不确定进度模式
        self.loading_progress.setFixedHeight(3)
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

        self.symbol_combo = QtWidgets.QComboBox(self)
        self.symbol_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.symbol_combo.setVisible(False)

        self.symbol_search = QtWidgets.QLineEdit(self)
        self.symbol_search.setPlaceholderText("输入代码或名称搜索")
        self.symbol_search.setClearButtonEnabled(True)

        self.strategy_button: Optional[QtWidgets.QToolButton] = None

        self.left_nav: Optional[SnowLeftNav] = None
        self.stock_panel: Optional[QtWidgets.QWidget] = None
        self.symbol_tabs: Optional[QtWidgets.QTabBar] = None
        self.all_symbol_list: Optional[QtWidgets.QListView] = None
        self.favorite_symbol_list: Optional[QtWidgets.QListWidget] = None
        self.symbol_list_manager: Optional[SymbolListManager] = None
        self.pages: Optional[QtWidgets.QStackedWidget] = None
        self.quotes_view: Optional[SnowQuotesPage] = None
        self.data_view: Optional[SnowDataPage] = None
        self.quotes_page: Optional[QtWidgets.QWidget] = None
        self.data_page: Optional[QtWidgets.QWidget] = None
        self.data_dir_value_label: Optional[QtWidgets.QLabel] = None
        self.data_db_value_label: Optional[QtWidgets.QLabel] = None
        self.import_status_label: Optional[QtWidgets.QLabel] = None
        self.data_page_progress: Optional[QtWidgets.QProgressBar] = None
        self.strategy_sidebar: Optional[QtWidgets.QWidget] = None
        self.strategy_panel_container: Optional[QtWidgets.QWidget] = None
        self.strategy_panel_layout: Optional[QtWidgets.QVBoxLayout] = None
        self.strategy_placeholder_label: Optional[QtWidgets.QLabel] = None
        self.strategy_panel_widget: Optional[QtWidgets.QWidget] = None
        self.strategy_panel_controller: Optional[StrategyPanelController] = None
        self.sample_symbol_entries: List[Dict[str, Any]] = load_sample_symbols()
        self.window_min_button: Optional[QtWidgets.QToolButton] = None
        self.window_max_button: Optional[QtWidgets.QToolButton] = None
        self.window_close_button: Optional[QtWidgets.QToolButton] = None
        self.top_header: Optional[QtWidgets.QWidget] = None
        self.header_drag_area: Optional[QtWidgets.QWidget] = None
        self._window_drag_offset: Optional[QtCore.QPoint] = None

        self._create_actions()
        self._build_main_layout()
        self.menuBar().setVisible(False)

        self.strategy_panel_controller = StrategyPanelController(host=self)
        self.log_console = LogConsole(parent=self)
        self.kline_controller: Optional[KLineControllerType] = None
        self.workbench_controller: Optional[StrategyWorkbenchControllerType] = None
        self.echarts_dialog: Optional[QtWidgets.QDialog] = None

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

        self._init_kline_controller()
        self._init_workbench_controller()

        self.statusBar().showMessage("就绪")
        # 导入进度条(用于导入过程的可视反馈)
        self.import_progress = QtWidgets.QProgressBar(self)
        self.import_progress.setVisible(False)
        self.import_progress.setFixedWidth(150)
        self.statusBar().addPermanentWidget(self.import_progress)
        self.import_controller = ImportController(
            parent=self,
            data_dir_getter=lambda: self.data_dir,
            db_path_getter=lambda: self.db_path,
            import_worker_cls=ImportWorker,
            log_handler=self.append_log,
            log_reset=self.log_console.reset,
            ensure_log_dialog=self.show_log_console,
            status_setter=self._set_import_status,
            status_bar=self.statusBar(),
            import_progress=self.import_progress,
            data_progress_getter=lambda: self.data_page_progress,
            refresh_symbols_async=self.refresh_symbols_async,
            action_choose_dir=self.action_choose_dir,
            action_import_append=self.action_import_append,
            action_import_replace=self.action_import_replace,
        )
        if self.kline_controller:
            self.kline_controller.load_initial_chart()

    # Insert MainWindow methods (copied from tradingview_kline.py)
    def _create_actions(self) -> None:
        self.action_choose_dir = QtWidgets.QAction("选择数据目录...", self)
        self.action_choose_dir.triggered.connect(self.choose_data_directory)

        self.action_choose_db = QtWidgets.QAction("选择数据库文件...", self)
        self.action_choose_db.triggered.connect(self.choose_database_file)

        self.action_import_append = QtWidgets.QAction("导入(追加)", self)
        self.action_import_append.triggered.connect(lambda: self.start_import(False))
        self.action_import_append.setEnabled(False)

        self.action_import_replace = QtWidgets.QAction("导入(重建)", self)
        self.action_import_replace.triggered.connect(lambda: self.start_import(True))
        self.action_import_replace.setEnabled(False)

        self.action_refresh_symbols = QtWidgets.QAction("刷新标的列表", self)
        self.action_refresh_symbols.triggered.connect(self.refresh_symbols)

        self.action_show_echarts_demo = QtWidgets.QAction("ECharts 演示", self)
        self.action_show_echarts_demo.triggered.connect(self._show_echarts_demo)

        style = QtWidgets.QApplication.style()
        try:
            self.action_choose_dir.setIcon(style.standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
            self.action_choose_db.setIcon(style.standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))
            self.action_import_append.setIcon(style.standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
            self.action_import_replace.setIcon(style.standardIcon(QtWidgets.QStyle.SP_TrashIcon))
            self.action_refresh_symbols.setIcon(style.standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        except Exception:
            pass

        self.action_choose_dir.setToolTip("选择本地数据目录(Excel/CSV)并导入至数据库")
        self.action_choose_db.setToolTip("选择或创建 SQLite 数据库文件用于保存行情 K 线")
        self.action_import_append.setToolTip("将新数据追加到现有数据表中(非破坏性)")
        self.action_import_replace.setToolTip("删除并重建目标数据表,以新数据覆盖现有记录")
        self.action_refresh_symbols.setToolTip("刷新数据库中的标的列表")

    def _build_main_layout(self) -> None:
        container = QtWidgets.QWidget(self)
        outer = QtWidgets.QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        nav_items = {
            "行情": self.switch_to_quotes,
            "数据": self.switch_to_data,
            "策略": self._focus_strategy_sidebar,
        }
        self.left_nav = SnowLeftNav(parent=container, nav_items=nav_items)
        outer.addWidget(self.left_nav)

        content_container = QtWidgets.QWidget(container)
        content_layout = QtWidgets.QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.symbol_search.setPlaceholderText("代码/名称/拼音")
        self.symbol_search.setFixedHeight(32)
        self.symbol_search.setMinimumWidth(320)
        self.top_header = SnowTopHeader(
            parent=content_container,
            search_widget=self.symbol_search,
            on_strategy_clicked=self._focus_strategy_sidebar,
            on_minimize=self.showMinimized,
            on_maximize_toggle=self._toggle_max_restore,
            on_close=self.close,
        )
        self.header_drag_area = self.top_header.drag_area
        if self.header_drag_area:
            self.header_drag_area.installEventFilter(self)
        self.strategy_button = None
        self.window_min_button = self.top_header.min_button
        self.window_max_button = self.top_header.max_button
        self.window_close_button = self.top_header.close_button
        content_layout.addWidget(self.top_header)

        self.pages = QtWidgets.QStackedWidget(content_container)
        self.quotes_view = SnowQuotesPage(host=self, parent=self.pages)
        self.quotes_page = self.quotes_view
        self._init_symbol_list_manager()
        self.data_view = SnowDataPage(host=self, parent=self.pages)
        self.data_page = self.data_view
        if self.quotes_page:
            self.pages.addWidget(self.quotes_page)
        if self.data_page:
            self.pages.addWidget(self.data_page)
        content_layout.addWidget(self.pages, 1)

        outer.addWidget(content_container, 1)

        self.setCentralWidget(container)
        self._refresh_data_page_labels()
        self._set_import_status("待命")
        self.switch_to_quotes()
        self._update_window_controls()
        self._set_symbol_panel_visible(False)

    def _init_symbol_list_manager(self) -> None:
        if self.all_symbol_list is None:
            return
        self.symbol_list_manager = SymbolListManager(
            list_view=self.all_symbol_list,
            select_symbol=self._select_symbol_from_manager,
            current_table_getter=self._current_symbol_table,
            log_handler=self.append_log,
            sample_entries=self.sample_symbol_entries,
        )

    def switch_to_quotes(self) -> None:
        if self.pages and self.quotes_page:
            self.pages.setCurrentWidget(self.quotes_page)
        if self.left_nav:
            self.left_nav.set_active("行情")
        self._collapse_strategy_sidebar()

    def switch_to_data(self) -> None:
        if self.pages and self.data_page:
            self.pages.setCurrentWidget(self.data_page)
        if self.left_nav:
            self.left_nav.set_active("数据")
        self._collapse_strategy_sidebar()

    def _focus_strategy_sidebar(self) -> None:
        if self.strategy_panel_controller:
            self.strategy_panel_controller.focus_sidebar()

    def _collapse_strategy_sidebar(self) -> None:
        sidebar = self.strategy_sidebar
        splitter = self.body_splitter
        if not sidebar or not splitter:
            return
        sidebar.setVisible(False)
        left_width = self.stock_panel.width() if self.stock_panel else 280
        total_width = splitter.width() or sum(splitter.sizes()) or (left_width + 800)
        center_width = max(total_width - left_width, 600)
        splitter.setSizes([left_width, center_width, 0])

    def _format_path(self, path_value: Optional[Path]) -> str:
        if isinstance(path_value, Path):
            try:
                return str(path_value.resolve())
            except Exception:
                return str(path_value)
        return "未选择"

    def _refresh_data_page_labels(self) -> None:
        if self.data_dir_value_label is not None:
            self.data_dir_value_label.setText(self._format_path(self.data_dir))
        if self.data_db_value_label is not None:
            self.data_db_value_label.setText(self._format_path(self.db_path))

    def _set_import_status(self, text: str) -> None:
        if self.import_status_label is not None:
            self.import_status_label.setText(text)

    def _set_symbol_panel_visible(self, visible: bool) -> None:
        if self.stock_panel:
            self.stock_panel.setVisible(visible)

    def _toggle_max_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._update_window_controls()

    def _update_window_controls(self) -> None:
        if not self.window_max_button:
            return
        try:
            style = QtWidgets.QApplication.style()
            icon_role = (
                QtWidgets.QStyle.SP_TitleBarNormalButton if self.isMaximized() else QtWidgets.QStyle.SP_TitleBarMaxButton
            )
            self.window_max_button.setIcon(style.standardIcon(icon_role))
        except Exception:
            pass

    def changeEvent(self, event: QtCore.QEvent) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.WindowStateChange:
            self._update_window_controls()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._ensure_sample_symbols()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # type: ignore[override]
        if obj == self.header_drag_area and self.header_drag_area is not None:
            if event.type() == QtCore.QEvent.MouseButtonPress and isinstance(event, QtGui.QMouseEvent):
                if event.button() == QtCore.Qt.LeftButton:
                    self._window_drag_offset = event.globalPos() - self.frameGeometry().topLeft()
                    return True
            if event.type() == QtCore.QEvent.MouseMove and isinstance(event, QtGui.QMouseEvent):
                if event.buttons() & QtCore.Qt.LeftButton and self._window_drag_offset and not self.isMaximized():
                    self.move(event.globalPos() - self._window_drag_offset)
                    return True
            if event.type() == QtCore.QEvent.MouseButtonRelease and isinstance(event, QtGui.QMouseEvent):
                if event.button() == QtCore.Qt.LeftButton:
                    self._window_drag_offset = None
                    return True
            if event.type() == QtCore.QEvent.MouseButtonDblClick and isinstance(event, QtGui.QMouseEvent):
                if event.button() == QtCore.Qt.LeftButton:
                    self._toggle_max_restore()
                    return True
        return super().eventFilter(obj, event)

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
        if self.kline_controller:
            self.kline_controller.symbols_updated.connect(self._on_symbols_updated)
            self.kline_controller.symbol_changed.connect(self._on_symbol_changed)

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
        self.workbench_controller = controller

    def _on_symbols_updated(self, entries: List[Dict[str, Any]]) -> None:
        if not self.symbol_list_manager:
            return
        dataset = entries or self.sample_symbol_entries
        self.symbol_list_manager.populate(dataset, is_sample=not bool(entries))
        if entries:
            self.symbol_list_manager.highlight_current()
            self._set_symbol_panel_visible(True)

    def _on_symbol_changed(self, table_name: str) -> None:
        if self.symbol_list_manager:
            self.symbol_list_manager.highlight_identifier(table_name)

    def _ensure_sample_symbols(self) -> None:
        if self.symbol_list_manager:
            self.symbol_list_manager.ensure_sample_symbols()

    def _current_symbol_table(self) -> Optional[str]:
        if self.kline_controller and getattr(self.kline_controller, "current_table", None):
            return self.kline_controller.current_table
        return None

    def _select_symbol_from_manager(self, table_name: str) -> None:
        if self.kline_controller:
            self.kline_controller.select_symbol(table_name)

    def focus_chart(self) -> None:
        if self.kline_controller and hasattr(self.kline_controller, "focus_chart"):
            self.kline_controller.focus_chart()
        else:
            try:
                self.web_view.setFocus()
            except Exception:
                pass

    def _show_echarts_demo(self) -> None:
        if render_echarts_demo is None:
            QtWidgets.QMessageBox.warning(self, "渲染模块缺失", "当前环境缺少 ECharts 模板，无法展示示例。")
            return
        candles = list(getattr(self.kline_controller, "current_candles", []) or [])
        if not candles:
            QtWidgets.QMessageBox.information(self, "缺少数据", "请先加载一只股票到主图，再查看示例。")
            return
        markers = list(getattr(self.kline_controller, "current_markers", []) or [])
        overlays = list(getattr(self.kline_controller, "current_overlays", []) or [])
        try:
            html = render_echarts_demo(candles, markers, overlays)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "渲染失败", f"生成示例时出错: {exc}")
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("ECharts K线演示")
        dialog.resize(960, 620)
        layout = QtWidgets.QVBoxLayout(dialog)
        view = QWebEngineView(dialog)
        base_url = QtCore.QUrl.fromLocalFile(str(ECHARTS_TEMPLATE_PATH))
        view.setHtml(html, base_url)
        layout.addWidget(view)
        self.echarts_dialog = dialog
        dialog.exec_()

    def show_log_console(self, *, show: bool = False) -> None:
        self.log_console.ensure(show=show)

    def append_log(self, message: str, *, force_show: bool = False) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.log_console.append(entry, force_show=force_show)

    def _on_js_console_message(self, message: str) -> None:
        self.append_log(f"[JS] {message}")

    def choose_data_directory(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "选择包含 Excel/CSV 的目录")
        if not directory:
            return

        self.data_dir = Path(directory)
        self.append_log(f"已选择数据目录: {self.data_dir}")
        self.statusBar().showMessage(f"数据目录: {self.data_dir}")
        self.action_import_append.setEnabled(True)
        self.action_import_replace.setEnabled(True)
        self._refresh_data_page_labels()
        self._set_import_status("数据目录已就绪，等待导入")

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
        self.append_log(f"数据库路径已更新为: {self.db_path}")
        self._refresh_data_page_labels()
        # Refresh symbols asynchronously to avoid blocking UI when DB is large.
        self.refresh_symbols_async()

    def start_import(self, replace: Optional[bool] = None) -> None:
        if self.import_controller:
            self.import_controller.start_import(replace)

    def refresh_symbols(self, select: Optional[str] = None) -> List[str]:
        if self.kline_controller:
            return self.kline_controller.refresh_symbols(select)
        return []

    def refresh_symbols_async(self, select: Optional[str] = None) -> None:
        if self.kline_controller:
            self.kline_controller.refresh_symbols_async(select)
# End of main_ui.py
