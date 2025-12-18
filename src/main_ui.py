from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView  # type: ignore[import-not-found]

from .ui.controllers import ImportController, LogConsole, StrategyPanelController, SymbolListManager
from .ui.data import load_sample_symbols
from .ui.pages import SnowDataPage, SnowQuotesPage
from .ui.widgets.left_nav import SnowLeftNav
from .ui.widgets.top_header import SnowTopHeader
from .data.watchlist_store import WatchlistStore

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
    from .data.workers import ImportWorker, TushareSyncWorker, TushareTestWorker  # type: ignore[import-not-found]
except Exception:
    ImportWorker = None
    TushareSyncWorker = None
    TushareTestWorker = None

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
        self.tushare_token_input: Optional[QtWidgets.QLineEdit] = None
        self.tushare_status_label: Optional[QtWidgets.QLabel] = None
        self.tushare_start_date: Optional[QtWidgets.QDateEdit] = None
        self.tushare_end_date: Optional[QtWidgets.QDateEdit] = None
        self.tushare_token_path: Path = Path.home() / ".tushare_token"
        self.tushare_token: Optional[str] = self._load_tushare_token()
        self._tushare_thread: Optional[QtCore.QThread] = None
        self._tushare_worker: Optional[QtCore.QObject] = None
        self._tushare_test_thread: Optional[QtCore.QThread] = None
        self._tushare_test_worker: Optional[QtCore.QObject] = None
        self.strategy_sidebar: Optional[QtWidgets.QWidget] = None
        self.strategy_panel_container: Optional[QtWidgets.QWidget] = None
        self.strategy_panel_layout: Optional[QtWidgets.QVBoxLayout] = None
        self.strategy_placeholder_label: Optional[QtWidgets.QLabel] = None
        self.strategy_panel_widget: Optional[QtWidgets.QWidget] = None
        self.strategy_panel_controller: Optional[StrategyPanelController] = None
        self.sample_symbol_entries: List[Dict[str, Any]] = load_sample_symbols()
        self.watchlist_db_path: Path = Path(__file__).resolve().parent / "data" / "watchlists.db"
        try:
            self.watchlist_store = WatchlistStore(self.watchlist_db_path)
        except Exception as exc:
            print(f"[UI] Failed to init watchlist store: {exc}")
            self.watchlist_store = WatchlistStore()
        self.current_watchlist_id: Optional[int] = None
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
            # Delay initial data load to avoid blocking UI construction
            QtCore.QTimer.singleShot(0, self.kline_controller.load_initial_chart)

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
            selection_mode=QtWidgets.QAbstractItemView.ExtendedSelection,
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
        if self.tushare_token_input is not None and self.tushare_token:
            self.tushare_token_input.setText(self.tushare_token)
        if self.tushare_status_label is not None:
            self.tushare_status_label.setText("等待同步")

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
            watchlist_adder=self.add_symbols_to_watchlist,
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

    # --- Watchlist helpers -------------------------------------------------
    def ensure_default_watchlist(self) -> int:
        try:
            lists = self.watchlist_store.list_watchlists()
        except Exception:
            lists = []
        if not lists:
            return -1
        wid = int(lists[0][0])
        self.current_watchlist_id = wid
        return wid

    def add_symbols_to_watchlist(self, items: List[Tuple[str, str]], watchlist_id: Optional[int] = None) -> None:
        if not items:
            return
        wid = watchlist_id or self.current_watchlist_id
        if wid is None or wid <= 0:
            QtWidgets.QMessageBox.information(self, "缺少自选分组", "请先在“自选”页创建分组后再添加股票。")
            return
        try:
            self.watchlist_store.add_symbols(wid, items)
            self.append_log(f"已加入自选: {', '.join(sym for sym, _ in items)}")
            if self.quotes_view:
                self.quotes_view.refresh_watchlist_view(wid)
        except Exception as exc:
            self.append_log(f"加入自选失败: {exc}")

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

    # --- Tushare sync helpers --------------------------------------------
    def _load_tushare_token(self) -> Optional[str]:
        try:
            text = self.tushare_token_path.read_text(encoding="utf-8").strip()
            return text or None
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def _save_tushare_token_value(self, token: str) -> None:
        token = token.strip()
        if not token:
            return
        try:
            self.tushare_token_path.write_text(token, encoding="utf-8")
            self.tushare_token = token
            self.append_log("已保存 Tushare Token")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "保存失败", f"写入 token 文件失败: {exc}")

    def save_tushare_token(self) -> None:
        if self.tushare_token_input:
            token = self.tushare_token_input.text()
            if token:
                self._save_tushare_token_value(token)
                self._set_import_status("已保存 Tushare Token")

    def start_tushare_update(self) -> None:
        if TushareSyncWorker is None:
            QtWidgets.QMessageBox.warning(self, "缺少依赖", "未找到 TushareSyncWorker，请检查依赖")
            return
        token = ""
        if self.tushare_token_input:
            token = self.tushare_token_input.text().strip()
        if not token:
            token = self.tushare_token or ""
        if not token:
            QtWidgets.QMessageBox.information(self, "缺少 Token", "请先粘贴 Tushare Token")
            return
        self.tushare_token = token
        if not self.db_path:
            QtWidgets.QMessageBox.warning(self, "缺少数据库", "未设置数据库路径")
            return
        start_date = None
        end_date = None
        if self.tushare_start_date:
            start_date = self.tushare_start_date.date().toString("yyyyMMdd")
        if self.tushare_end_date:
            end_date = self.tushare_end_date.date().toString("yyyyMMdd")
        if self.data_page_progress:
            self.data_page_progress.setRange(0, 0)
            self.data_page_progress.setVisible(True)
        if self.import_status_label:
            self.import_status_label.setText("Tushare 更新中...")
        if self.tushare_status_label:
            self.tushare_status_label.setText("正在同步日线...")

        worker = TushareSyncWorker(
            db_path=self.db_path,
            token=token,
            lookback_days=180,
            mode="by_date",
            start_date=start_date,
            end_date=end_date,
        )
        thread = QtCore.QThread(self)
        self._tushare_thread = thread
        self._tushare_worker = worker
        worker.moveToThread(thread)
        worker.progress.connect(lambda msg: self.append_log(f"[Tushare] {msg}"))
        worker.progress_count.connect(self._on_tushare_progress)
        worker.finished.connect(self._on_tushare_finished)
        worker.failed.connect(self._on_tushare_failed)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def start_tushare_test(self) -> None:
        if TushareTestWorker is None:
            QtWidgets.QMessageBox.warning(self, "缺少依赖", "未找到 TushareTestWorker，请检查依赖")
            return
        token = ""
        if self.tushare_token_input:
            token = self.tushare_token_input.text().strip()
        if token:
            self.tushare_token = token  # 优先使用输入框
        if not token and self.tushare_token:
            token = self.tushare_token
        if not token:
            QtWidgets.QMessageBox.information(self, "缺少 Token", "请先粘贴 Tushare Token")
            return
        if self.data_page_progress:
            self.data_page_progress.setRange(0, 0)
            self.data_page_progress.setVisible(True)
        if self.tushare_status_label:
            self.tushare_status_label.setText("测试中...")

        worker = TushareTestWorker(token=token)
        thread = QtCore.QThread(self)
        self._tushare_test_thread = thread
        self._tushare_test_worker = worker
        worker.moveToThread(thread)
        worker.finished.connect(self._on_tushare_test_finished)
        worker.failed.connect(self._on_tushare_test_failed)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_tushare_finished(self, stats: object) -> None:
        if self.data_page_progress:
            self.data_page_progress.setVisible(False)
            self.data_page_progress.setRange(0, 1)
            self.data_page_progress.setValue(0)
        summary = getattr(stats, "__dict__", {}) if hasattr(stats, "__dict__") else {}
        success = summary.get("succeeded", "?")
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)
        self.append_log(f"[Tushare] 完成，成功 {success}，失败 {failed}，跳过 {skipped}")
        if self.import_status_label:
            self.import_status_label.setText("Tushare 更新完成")
        if self.tushare_status_label:
            self.tushare_status_label.setText(f"完成：成功 {success}，失败 {failed}，跳过 {skipped}")
        # 刷新标的列表，让行情页同步最新表
        self.refresh_symbols_async()

    def _on_tushare_failed(self, message: str) -> None:
        if self.data_page_progress:
            self.data_page_progress.setVisible(False)
            self.data_page_progress.setRange(0, 1)
            self.data_page_progress.setValue(0)
        self.append_log(f"[Tushare] 失败: {message}", force_show=True)
        QtWidgets.QMessageBox.critical(self, "Tushare 同步失败", message)
        if self.import_status_label:
            self.import_status_label.setText("Tushare 更新失败")
        if self.tushare_status_label:
            self.tushare_status_label.setText("同步失败")

    def _on_tushare_progress(self, current: int, total: int) -> None:
        if not self.data_page_progress:
            return
        self.data_page_progress.setVisible(True)
        if total <= 0:
            self.data_page_progress.setRange(0, 0)
            return
        self.data_page_progress.setRange(0, total)
        self.data_page_progress.setValue(max(0, min(current, total)))

    def _on_tushare_test_finished(self, message: str) -> None:
        if self.data_page_progress:
            self.data_page_progress.setVisible(False)
            self.data_page_progress.setRange(0, 1)
            self.data_page_progress.setValue(0)
        self.append_log(f"[Tushare测试] {message}", force_show=True)
        QtWidgets.QMessageBox.information(self, "Tushare 测试", message)
        if self.tushare_status_label:
            self.tushare_status_label.setText("测试通过")

    def _on_tushare_test_failed(self, message: str) -> None:
        if self.data_page_progress:
            self.data_page_progress.setVisible(False)
            self.data_page_progress.setRange(0, 1)
            self.data_page_progress.setValue(0)
        self.append_log(f"[Tushare测试] {message}", force_show=True)
        QtWidgets.QMessageBox.warning(self, "Tushare 测试失败", message)
        if self.tushare_status_label:
            self.tushare_status_label.setText("测试失败")
# End of main_ui.py
