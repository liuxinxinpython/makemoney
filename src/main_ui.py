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
    from .data.workers import ImportWorker, SymbolLoadWorker, CandleLoadWorker  # type: ignore[import-not-found]
except Exception:
    ImportWorker = None
    SymbolLoadWorker = None
    CandleLoadWorker = None

try:
    from .rendering import render_html, build_mock_candles, load_maotai_candles, TEMPLATE_PATH  # type: ignore[import-not-found]
except Exception:
    render_html = None
    build_mock_candles = None
    load_maotai_candles = None
    TEMPLATE_PATH = Path(__file__).parent / 'rendering' / 'templates' / 'tradingview_template.html'

try:
    from .data.data_loader import load_candles_from_sqlite  # type: ignore[import-not-found]
except Exception:
    load_candles_from_sqlite = None

try:
    from .displays import DisplayManager, DisplayResult
except Exception:
    DisplayManager = None
    DisplayResult = None

try:
    from .strategies.zigzag_wave_peaks_valleys import ZigZagWavePeaksValleysStrategy
except Exception:
    ZigZagWavePeaksValleysStrategy = None

try:
    from .ui import StrategyWorkbenchPanel
except Exception:
    StrategyWorkbenchPanel = None

try:
    from .research import (
        StrategyContext,
        StrategyDefinition,
        StrategyParameter,
        StrategyRegistry,
        StrategyRunResult,
        global_strategy_registry,
    )
except Exception:
    StrategyContext = None
    StrategyDefinition = None
    StrategyParameter = None
    StrategyRegistry = None
    StrategyRunResult = None
    global_strategy_registry = None


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

        from .rendering import render_html as _; _
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
        self.symbol_combo.currentIndexChanged.connect(self.on_symbol_index_changed)

        self.symbol_search = QtWidgets.QLineEdit(self)
        self.symbol_search.setPlaceholderText("输入代码或名称搜索")
        self.symbol_search.setClearButtonEnabled(True)
        self.symbol_search.returnPressed.connect(self._activate_search_result)
        self.symbol_search.textChanged.connect(self._on_search_text_changed)

        self.symbol_entries: List[Dict[str, str]] = []
        self.filtered_symbol_entries: List[Dict[str, str]] = []
        self.current_symbol: Optional[str] = None
        self.current_symbol_name: str = ""
        self.current_table: Optional[str] = None
        self.current_markers: List[Dict[str, Any]] = []
        self.current_overlays: List[Dict[str, Any]] = []
        self.current_candles: List[Dict[str, Any]] = []
        # background workers and threads
        self._symbol_load_thread: Optional[QtCore.QThread] = None
        self._symbol_loader: Optional[QtCore.QObject] = None
        self._candle_load_thread: Optional[QtCore.QThread] = None
        self._candle_loader: Optional[QtCore.QObject] = None
        self.log_dialog: Optional[QtWidgets.QDialog] = None
        self.log_text: Optional[QtWidgets.QTextEdit] = None
        self.log_history: List[str] = []
        self.strategy_definitions: List[Dict[str, Any]] = []
        self.menu_strategy: Optional[QtWidgets.QMenu] = None
        self.menu_view: Optional[QtWidgets.QMenu] = None
        self.strategy_registry: Optional[StrategyRegistry] = None
        self.workbench_panel: Optional[StrategyWorkbenchPanel] = None
        self.workbench_dock: Optional[QtWidgets.QDockWidget] = None
        self.action_toggle_workbench: Optional[QtWidgets.QAction] = None

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
        self._initialize_strategies()
        self._setup_strategy_workbench()

        self.statusBar().showMessage("就绪")
        # 导入进度条(用于导入过程的可视反馈)
        self.import_progress = QtWidgets.QProgressBar(self)
        self.import_progress.setVisible(False)
        self.import_progress.setFixedWidth(150)
        self.statusBar().addPermanentWidget(self.import_progress)
        self._load_initial_chart()

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

        self.menu_strategy = self.menuBar().addMenu("选股")
        self.menu_view = self.menuBar().addMenu("视图")
        self.action_toggle_workbench = QtWidgets.QAction("显示策略工作台", self)
        self.action_toggle_workbench.setCheckable(True)
        self.action_toggle_workbench.setChecked(True)
        self.action_toggle_workbench.triggered.connect(self._toggle_workbench_visibility)
        if StrategyWorkbenchPanel is None or global_strategy_registry is None:
            self.action_toggle_workbench.setEnabled(False)
        self.menu_view.addAction(self.action_toggle_workbench)

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
        # 移除工具栏中的"选股"下拉,仅保留菜单栏版本

    def _initialize_strategies(self) -> None:
        self.strategy_definitions = []
        self._register_strategy(
            key="zigzag_wave_peaks_valleys",
            title="ZigZag波峰波谷",
            handler=self.scan_zigzag_wave_peaks_valleys,
            requires_selector=False,
            description="使用 ZigZag 算法在图表中识别价格数据的波峰与波谷形态",
        )
        self._rebuild_strategy_menus()

    def _setup_strategy_workbench(self) -> None:
        if self.workbench_dock is not None:
            return
        if StrategyWorkbenchPanel is None or global_strategy_registry is None:
            return
        try:
            self.strategy_registry = global_strategy_registry()
        except Exception:
            self.strategy_registry = None
            return

        self._register_workbench_strategies()

        if not self.strategy_registry:
            return

        panel = StrategyWorkbenchPanel(
            registry=self.strategy_registry,
            universe_provider=self._workbench_universe,
            db_path_provider=lambda: self.db_path,
            preview_handler=self._run_workbench_preview,
            chart_focus_handler=self._focus_chart_view,
            load_symbol_handler=self._load_symbol_from_workbench,
            parent=self,
        )
        dock = QtWidgets.QDockWidget("策略工作台", self)
        dock.setObjectName("strategy_workbench_dock")
        dock.setWidget(panel)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        dock.visibilityChanged.connect(self._on_workbench_visibility_changed)

        self.workbench_panel = panel
        self.workbench_dock = dock

        if self.action_toggle_workbench:
            self.action_toggle_workbench.setEnabled(True)
            self.action_toggle_workbench.blockSignals(True)
            self.action_toggle_workbench.setChecked(True)
            self.action_toggle_workbench.blockSignals(False)

    def _register_workbench_strategies(self) -> None:
        if not (self.strategy_registry and StrategyDefinition and StrategyParameter):
            return
        if self.strategy_registry.get("zigzag_wave_peaks_valleys"):
            return

        definition = StrategyDefinition(
            key="zigzag_wave_peaks_valleys",
            title="ZigZag波峰波谷",
            description="识别 ZigZag 波动形态, 输出波峰/波谷标记与状态信息",
            handler=self._zigzag_strategy_handler,
            category="形态识别",
            parameters=[
                StrategyParameter(
                    key="min_reversal",
                    label="最小反转(%)",
                    type="number",
                    default=5.0,
                    description="忽略幅度低于该百分比的价格波动",
                )
            ],
            tags=["形态识别", "波动策略"],
        )
        self.strategy_registry.register(definition)

    def _zigzag_strategy_handler(self, context: "StrategyContext") -> "StrategyRunResult":
        if ZigZagWavePeaksValleysStrategy is None or StrategyRunResult is None:
            raise RuntimeError("ZigZag 策略不可用")

        try:
            min_pct = float(context.params.get("min_reversal", 5.0))
        except (TypeError, ValueError):
            min_pct = 5.0
        min_reversal = max(0.0005, min_pct / 100.0)

        strategy = ZigZagWavePeaksValleysStrategy(min_reversal=min_reversal)
        raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)

        markers: List[Dict[str, Any]] = []
        overlays: List[Dict[str, Any]] = []
        status_message: Optional[str] = None

        if raw_result is None:
            pass
        elif DisplayResult is not None and isinstance(raw_result, DisplayResult):
            markers = list(getattr(raw_result, "markers", []) or [])
            overlays = list(getattr(raw_result, "overlays", []) or [])
            status_message = getattr(raw_result, "status_message", None)
        else:
            markers = list(raw_result.get("markers", []) or [])  # type: ignore[union-attr]
            overlays = list(raw_result.get("overlays", []) or [])  # type: ignore[union-attr]
            status_message = raw_result.get("status_message")  # type: ignore[union-attr]

        return StrategyRunResult(
            strategy_name="zigzag_wave_peaks_valleys",
            markers=markers,
            overlays=overlays,
            status_message=status_message,
        )

    def _run_workbench_preview(self, strategy_key: str, params: Dict[str, object]) -> Optional["StrategyRunResult"]:
        if not self.strategy_registry or StrategyContext is None:
            raise RuntimeError("策略工作台不可用")
        if not self.current_table:
            raise RuntimeError("请先选择标的")
        if not self.db_path.exists():
            raise RuntimeError("数据库文件不存在")

        context = StrategyContext(
            db_path=self.db_path,
            table_name=self.current_table,
            symbol=self.current_symbol or self.current_table,
            params=params,
            current_only=True,
        )
        result = self.strategy_registry.run_strategy(strategy_key, context)

        if result and load_candles_from_sqlite:
            data = load_candles_from_sqlite(self.db_path, self.current_table)
            if data:
                candles, volumes, instrument = data
                self.current_markers = list(result.markers)
                self.current_overlays = list(result.overlays)
                self._render_chart(candles, volumes, instrument, self.current_markers, self.current_overlays)
                if result.status_message:
                    self.statusBar().showMessage(result.status_message)

        return result

    def _workbench_universe(self) -> List[str]:
        universe: List[str] = []
        for entry in self.symbol_entries:
            table = entry.get("table")
            if table:
                universe.append(table)
        return universe

    def _focus_chart_view(self) -> None:
        if hasattr(self, "web_view"):
            try:
                self.web_view.setFocus()
            except Exception:
                pass

    def _load_symbol_from_workbench(self, table_name: str) -> None:
        if not table_name:
            return

        def _select_from(entries: List[Dict[str, str]]) -> bool:
            for idx, entry in enumerate(entries):
                target_table = entry.get("table")
                target_symbol = entry.get("symbol")
                if target_table == table_name or target_symbol == table_name:
                    self.symbol_combo.setCurrentIndex(idx)
                    return True
            return False

        if self.filtered_symbol_entries and _select_from(self.filtered_symbol_entries):
            return

        if self.symbol_search.text():
            self.symbol_search.blockSignals(True)
            self.symbol_search.clear()
            self.symbol_search.blockSignals(False)

        self._apply_symbol_filter(select=table_name, maintain_selection=False)

    def _toggle_workbench_visibility(self, checked: bool) -> None:
        if checked and self.workbench_dock is None:
            self._setup_strategy_workbench()

        if self.workbench_dock:
            self.workbench_dock.setVisible(checked)
            if checked:
                self.workbench_dock.raise_()
        elif self.action_toggle_workbench:
            self.action_toggle_workbench.blockSignals(True)
            self.action_toggle_workbench.setChecked(False)
            self.action_toggle_workbench.blockSignals(False)

    def _on_workbench_visibility_changed(self, visible: bool) -> None:
        if self.action_toggle_workbench:
            self.action_toggle_workbench.blockSignals(True)
            self.action_toggle_workbench.setChecked(visible)
            self.action_toggle_workbench.blockSignals(False)

    def _register_strategy(
        self,
        *,
        key: str,
        title: str,
        handler: Callable[[], None],
        requires_selector: bool = False,
        description: str = "",
    ) -> None:
        definition = {
            "key": key,
            "title": title,
            "handler": handler,
            "requires_selector": requires_selector,
            "description": description,
        }
        self.strategy_definitions.append(definition)

    def _strategy_enabled(self, definition: Dict[str, Any]) -> bool:
        if definition.get("requires_selector"):
            # 检查 volume_price_selector 模块是否可用（VolumePriceStrategy 依赖）
            try:
                from .data.volume_price_selector import ScanConfig
                return True
            except ImportError:
                return False
        return True

    def _rebuild_strategy_menus(self) -> None:
        if self.menu_strategy is None:
            return
        # toolbar strategy_menu removed; only 'menu_strategy' in the menubar remains
        self.menu_strategy.clear()

        created_actions: List[QtWidgets.QAction] = []
        for definition in self.strategy_definitions:
            action = QtWidgets.QAction(definition["title"], self)
            action.triggered.connect(definition["handler"])
            enabled = self._strategy_enabled(definition)
            action.setEnabled(enabled)
            description = definition.get("description")
            if description:
                action.setStatusTip(description)
                action.setToolTip(description)
            self.menu_strategy.addAction(action)
            created_actions.append(action)

        if not created_actions:
            placeholder_menu = QtWidgets.QAction("暂无可用策略", self)
            placeholder_menu.setEnabled(False)
            self.menu_strategy.addAction(placeholder_menu)
        else:
            pass

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

    def scan_zigzag_wave_peaks_valleys(self) -> None:
        """使用 ZigZag 算法检测当前标的的波峰与波谷"""
        if not self.current_table:
            QtWidgets.QMessageBox.warning(self, "未选择标的", "请先选择一个标的再执行 ZigZag 检测。")
            return

        if not self.db_path.exists():
            QtWidgets.QMessageBox.warning(self, "缺少数据库", "请先选择有效的 SQLite 数据库文件。")
            return

        if ZigZagWavePeaksValleysStrategy is None:
            QtWidgets.QMessageBox.critical(self, "缺少模块", "ZigZag 策略模块未正确安装。")
            return

        try:
            strategy = ZigZagWavePeaksValleysStrategy()
            result = strategy.scan_current_symbol(self.db_path, self.current_table)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "ZigZag 检测失败", str(exc))
            return

        if result is None:
            QtWidgets.QMessageBox.information(self, "未检出波峰波谷", "当前标的未检测到明显的 ZigZag 波峰波谷。")
            self.current_markers = []
            self.current_overlays = []
            data = load_candles_from_sqlite(self.db_path, self.current_table) if self.current_table else None
            if data:
                candles, volumes, instrument = data
                self._render_chart(candles, volumes, instrument, [], [])
            return

        markers = result.get("markers", []) if isinstance(result, dict) else result.markers
        status_message = result.get("status_message", "") if isinstance(result, dict) else result.status_message

        self.current_markers = markers
        self.current_overlays = []
        data = load_candles_from_sqlite(self.db_path, self.current_table) if self.current_table else None
        if data:
            candles, volumes, instrument = data
            self._render_chart(candles, volumes, instrument, markers, [])

        self.statusBar().showMessage(status_message or "ZigZag 检测完成")


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
        # Synchronous fallback (keeps existing behavior when called explicitly)
        self.symbol_entries = []
        self.filtered_symbol_entries = []

        if not self.db_path.exists():
            self.symbol_combo.blockSignals(True)
            self.symbol_combo.clear()
            self.symbol_combo.addItem("(无数据)", None)
            self.symbol_combo.setEnabled(False)
            self.symbol_combo.blockSignals(False)
            self.current_symbol = None
            self.current_table = None
            self.current_markers = []
            return []

        symbol_names: List[str] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()

                for (table_name,) in rows:
                    table = str(table_name)
                    entry: Dict[str, str] = {
                        "table": table,
                        "symbol": table.upper(),
                        "name": "",
                        "display": table.upper(),
                    }

                    try:
                        escaped = table.replace('"', '""')
                        meta = conn.execute(
                            f'SELECT symbol, name FROM "{escaped}" ORDER BY date DESC LIMIT 1'
                        ).fetchone()
                        if meta:
                            meta_symbol = meta[0] if len(meta) > 0 else None
                            meta_name = meta[1] if len(meta) > 1 else None
                            if isinstance(meta_symbol, str) and meta_symbol.strip():
                                entry["symbol"] = meta_symbol.strip().upper()
                            elif meta_symbol is not None:
                                entry["symbol"] = str(meta_symbol).strip().upper()
                            if isinstance(meta_name, str) and meta_name.strip():
                                entry["name"] = meta_name.strip()
                            elif meta_name is not None:
                                entry["name"] = str(meta_name).strip()
                    except Exception as exc:  # pragma: no cover - runtime feedback
                        self.append_log(f"璇诲彇 {table} 鍚嶇О澶辫触: {exc}")

                    entry["display"] = (
                        f"{entry['symbol']} 路 {entry['name']}"
                        if entry["name"]
                        else entry["symbol"]
                    )
                    self.symbol_entries.append(entry)
                    symbol_names.append(entry["symbol"]) if entry["symbol"] else None
        except Exception as exc:  # pragma: no cover - runtime failure feedback
            self.append_log(f"加载标的列表失败: {exc}")

        if not self.symbol_entries:
            self.symbol_combo.blockSignals(True)
            self.symbol_combo.clear()
            self.symbol_combo.addItem("(无数据)", None)
            self.symbol_combo.setEnabled(False)
            self.symbol_combo.blockSignals(False)
            self.current_symbol = None
            self.current_table = None
            return []

        self.symbol_combo.setEnabled(True)
        self._apply_symbol_filter(select=select, maintain_selection=False)
        return symbol_names

    def refresh_symbols_async(self, select: Optional[str] = None) -> None:
        # 显示加载进度
        self.loading_progress.setVisible(True)
        self.statusBar().showMessage("正在加载标的列表...")
        
        # Async symbol refresh: use SymbolLoadWorker and update UI when finished.
        # Try to load cache to provide instant response
        cached = None
        try:
            cache_file = Path(str(self.db_path) + '.symbols.json')
            if cache_file.exists():
                raw = cache_file.read_text(encoding='utf-8')
                cached = json.loads(raw)
                self.append_log(f"从缓存加载了 {len(cached)} 条标的记录")
        except Exception as e:
            self.append_log(f"缓存加载失败: {e}")
            cached = None

        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        if cached:
            # Set the symbol entries from cache immediately
            self.symbol_entries = cached
            self.filtered_symbol_entries = cached.copy()
            for entry in cached:
                self.symbol_combo.addItem(entry.get('display', entry.get('symbol', '')), entry.get('table'))
            self.symbol_combo.setEnabled(True)
            self.append_log(f"标的列表已从缓存加载，共 {len(cached)} 条")
            # Set initial selection if specified
            if select:
                for idx, entry in enumerate(cached):
                    if entry["table"] == select or entry["symbol"] == select:
                        self.symbol_combo.setCurrentIndex(idx)
                        break
            # 缓存命中后立即隐藏进度
            self.loading_progress.setVisible(False)
            self.statusBar().showMessage("就绪")
        else:
            self.symbol_combo.addItem('(加载中...)', None)
            self.symbol_combo.setEnabled(False)
            self.append_log("没有缓存，开始后台加载标的列表")

        self._symbol_load_thread = QtCore.QThread(self)
        self._symbol_loader = SymbolLoadWorker(self.db_path)
        self._symbol_loader.moveToThread(self._symbol_load_thread)
        self._symbol_load_thread.started.connect(self._symbol_loader.run)
        self._symbol_loader.progress.connect(self._on_symbol_load_progress)
        self._symbol_loader.finished.connect(lambda entries: self._on_symbol_load_finished(entries, select))
        self._symbol_loader.finished.connect(lambda entries: self._save_symbols_cache(entries))
        self._symbol_loader.failed.connect(self._on_symbol_load_failed)
        self._symbol_load_thread.start()

    def _on_symbol_load_progress(self, message: str) -> None:
        """处理标的加载过程中的状态提示"""
        self.statusBar().showMessage(message)

    def _on_symbol_load_failed(self, error_message: str) -> None:
        """处理标的加载失败"""
        self.append_log(f"标的加载失败: {error_message}")
        # 隐藏进度条
        self.loading_progress.setVisible(False)
        self.statusBar().showMessage("标的列表加载失败")

    def _on_symbol_load_finished(self, entries: List[Dict[str, str]], select: Optional[str]) -> None:
        # Called in the main thread via signal.
        try:
            self._symbol_load_thread.quit()
            self._symbol_load_thread.wait(2000)
        except Exception:
            pass
        self.symbol_entries = entries
        self.filtered_symbol_entries = entries.copy()
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        for entry in entries:
            self.symbol_combo.addItem(entry.get('display', entry.get('symbol', '')), entry.get('table'))
        self.symbol_combo.setEnabled(True)
        self.symbol_combo.blockSignals(False)
        self._apply_symbol_filter(select=select, maintain_selection=False)
        
        # 隐藏进度条
        self.loading_progress.setVisible(False)
        self.statusBar().showMessage("标的列表加载完成")
        
        # Auto-load the default/first symbol's chart asynchronously (if any) to avoid blocking.
        chosen = None
        if select:
            for entry in entries:
                if entry.get('table') == select or entry.get('symbol') == select:
                    chosen = entry
                    break
        if not chosen and entries:
            chosen = entries[0]
        if chosen:
            table_to_load = chosen.get('table')
            try:
                self._candle_load_thread = QtCore.QThread(self)
                self._candle_loader = CandleLoadWorker(self.db_path, table_to_load)
                self._candle_loader.moveToThread(self._candle_load_thread)
                self._candle_load_thread.started.connect(self._candle_loader.run)
                self._candle_loader.finished.connect(lambda data: self._on_candle_load_finished(data, chosen))
                self._candle_loader.failed.connect(lambda e: self.append_log(f"加载 K 线失败: {e}"))
                self._candle_load_thread.start()
            except Exception as exc:
                self.append_log(f"启动 K 线加载线程失败: {exc}")

    def _save_symbols_cache(self, entries: List[Dict[str, str]]) -> None:
        try:
            cache_file = Path(str(self.db_path) + '.symbols.json')
            cache_file.write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    def _on_candle_load_finished(self, data: object, chosen: Dict[str, str]) -> None:
        try:
            self._candle_load_thread.quit()
            self._candle_load_thread.wait(2000)
        except Exception:
            pass
        if data is None:
            self.append_log(f"无法加载 {chosen.get('symbol') or chosen.get('table')} 的行情数据。")
            # 隐藏进度条
            self.loading_progress.setVisible(False)
            self.statusBar().showMessage("数据加载失败")
            return
        try:
            candles, volumes, instrument = data
            self.current_table = chosen.get('table')
            self.current_symbol = instrument.get('symbol') or chosen.get('symbol')
            self.current_symbol_name = instrument.get('name') or chosen.get('name') or ''
            self.current_candles = list(candles) if candles else []
            self.current_volumes = list(volumes) if volumes else []
            self.current_instrument = instrument
            self.current_markers = []
            self.current_overlays = []
            self._render_chart(candles, volumes, instrument, self.current_markers, self.current_overlays)
            display = self.current_symbol_name or ''
            if display:
                self.statusBar().showMessage(f"当前标的: {self.current_symbol} · {display}")
            else:
                self.statusBar().showMessage(f"当前标的: {self.current_symbol}")
            
            # 隐藏进度条
            self.loading_progress.setVisible(False)
        except Exception as exc:
            self.append_log(f"渲染 K 线时失败: {exc}")
            # 隐藏进度条
            self.loading_progress.setVisible(False)
            self.statusBar().showMessage("数据加载失败")

    def _on_search_text_changed(self, _text: str) -> None:
        self._apply_symbol_filter(maintain_selection=True)

    def _activate_search_result(self) -> None:
        if not self.filtered_symbol_entries:
            QtWidgets.QApplication.beep()
            return
        self.symbol_combo.setCurrentIndex(0)

    def _apply_symbol_filter(self, select: Optional[str] = None, maintain_selection: bool = True) -> None:
        query = self.symbol_search.text().strip().lower()
        self.filtered_symbol_entries = []

        for entry in self.symbol_entries:
            haystacks = [entry.get("symbol", ""), entry.get("name", ""), entry.get("table", "")]
            haystacks = [text.lower() for text in haystacks if text]
            if not query or any(query in text for text in haystacks):
                self.filtered_symbol_entries.append(entry)

        self.append_log(
            f"过滤结果: query='{query}', 原始={len(self.symbol_entries)}, 保留={len(self.filtered_symbol_entries)}"
        )

        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()

        if not self.filtered_symbol_entries:
            placeholder = "(无匹配)" if query else "(无数据)"
            self.symbol_combo.addItem(placeholder, None)
            self.symbol_combo.setEnabled(False)
            if not query:
                self.current_table = None
                self.current_symbol = None
                self.current_symbol_name = ""
                self.current_markers = []
            self.symbol_combo.blockSignals(False)
            return

        self.symbol_combo.setEnabled(True)
        for entry in self.filtered_symbol_entries:
            self.symbol_combo.addItem(entry["display"])
            idx = self.symbol_combo.count() - 1
            self.symbol_combo.setItemData(idx, entry)

        target_identifier: Optional[str]
        if select:
            target_identifier = select
        elif maintain_selection and self.current_table:
            target_identifier = self.current_table
        else:
            target_identifier = None

        target_index = 0
        if target_identifier:
            for idx, entry in enumerate(self.filtered_symbol_entries):
                if entry["table"] == target_identifier or entry["symbol"] == target_identifier:
                    target_index = idx
                    break

        previous_table = self.current_table
        self.symbol_combo.setCurrentIndex(target_index)
        self.symbol_combo.blockSignals(False)

        selected_entry = self.filtered_symbol_entries[target_index]
        if previous_table != selected_entry["table"] or not maintain_selection:
            self.on_symbol_index_changed(target_index)

    def on_symbol_index_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.filtered_symbol_entries):
            return

        entry = self.filtered_symbol_entries[index]
        table_name = entry["table"]

        try:
            if getattr(self, "_candle_load_thread", None) is not None:
                try:
                    self._candle_load_thread.quit()
                    self._candle_load_thread.wait(2000)
                except Exception:
                    pass
        except Exception:
            pass

        # 显示加载进度
        self.loading_progress.setVisible(True)
        self.append_log(f"启动后台加载 K 线数据: {entry['display']}")
        self.statusBar().showMessage(f"正在加载 {entry['display']} 的 K 线数据...")
        self._candle_load_thread = QtCore.QThread(self)
        self._candle_loader = CandleLoadWorker(self.db_path, table_name)
        self._candle_loader.moveToThread(self._candle_load_thread)
        self._candle_load_thread.started.connect(self._candle_loader.run)
        self._candle_loader.finished.connect(lambda data, chosen=entry: self._on_candle_load_finished(data, chosen))
        self._candle_loader.failed.connect(lambda e: self.append_log(f"加载 K 线失败: {e}"))
        self._candle_load_thread.start()

    def _render_chart(
        self,
        candles: List[Dict[str, float]],
        volumes: List[Dict[str, float]],
        instrument: Optional[Dict[str, str]] = None,
        markers: Optional[List[Dict[str, Any]]] = None,
        overlays: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.current_candles = list(candles) if candles else []

        # Priority: use provided markers/overlays first, then fall back to display manager or current markers
        if markers is not None:
            current_markers = markers
        elif self.display_manager:
            current_markers = self.display_manager.get_current_markers()
        else:
            current_markers = self.current_markers

        if overlays is not None:
            current_overlays = overlays
        elif self.display_manager:
            current_overlays = self.display_manager.get_current_overlays()
        else:
            current_overlays = self.current_overlays

        # 调试输出
        print(f"DEBUG: Rendering chart with {len(current_markers)} markers")
        print(f"DEBUG: markers parameter: {markers is not None}, len: {len(markers) if markers else 0}")
        print(f"DEBUG: current_markers len: {len(current_markers)}")
        if current_markers:
            print(f"DEBUG: First marker: {current_markers[0]}")
        else:
            print("DEBUG: current_markers is empty!")

        html = render_html(candles, volumes, instrument, current_markers, current_overlays)
        base_url = QtCore.QUrl.fromLocalFile(str(TEMPLATE_PATH))
        self.web_view.setHtml(html, base_url)

    def _load_initial_chart(self) -> None:
        # 显示加载进度
        self.loading_progress.setVisible(True)
        self.statusBar().showMessage("正在加载数据...")
        
        # Use async refresh to enumerate symbols and then load first symbol's candles on completion.
        self.refresh_symbols_async()

        data = load_maotai_candles()
        if data is None:
            candles, volumes, instrument = build_mock_candles()
            self.append_log("无法获取茅台数据，改用示例数据。")
        else:
            candles, volumes, instrument = data
            self.append_log("已加载茅台行情数据。")

        self.current_table = None
        self.current_symbol = instrument.get("symbol") if instrument else None
        self.current_symbol_name = instrument.get("name") if instrument else ""
        self.current_markers = []
        self.current_overlays = []
        self._render_chart(candles, volumes, instrument, self.current_markers, self.current_overlays)
        
        # 隐藏进度条
        self.loading_progress.setVisible(False)
        self.statusBar().showMessage("数据加载完成")



# End of main_ui.py
