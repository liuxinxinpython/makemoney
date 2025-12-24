from __future__ import annotations

# Allow running as a standalone module (e.g., `python workbench_panel.py`)
if __package__ in (None, ""):
    import sys
    from pathlib import Path as _Path

    project_root = _Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    __package__ = "src.ui.panels"

import csv
import math
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import os

from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]

from ...research import (
    BacktestEngine,
    BacktestRequest,
    BacktestResult,
    ScanRequest,
    ScanResult,
    StrategyDefinition,
    StrategyRegistry,
    StrategyRunResult,
    StrategyScanner,
)
from ...rendering.render_utils import render_backtest_equity
from ..echarts_preview_dialog import EChartsPreviewDialog


class StrategyWorkbenchPanel(QtWidgets.QWidget):
    '''Strategy research workbench inspired by professional terminals.'''

    def __init__(
        self,
        registry: StrategyRegistry,
        universe_provider: Callable[[], List[str]],
        selected_symbol_provider: Callable[[], Optional[str]],
        db_path_provider: Callable[[], Path],
        preview_handler: Callable[[str, Dict[str, object]], Optional[StrategyRunResult]],
        chart_focus_handler: Callable[[], None],
        load_symbol_handler: Callable[[str], None],
        render_markers_handler: Optional[Callable[[str, List[Dict[str, Any]], List[Dict[str, Any]]], None]] = None,
        add_to_watchlist: Optional[Callable[[List[Tuple[str, str]]], None]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName('StrategyWorkbench')
        self.registry = registry
        self.universe_provider = universe_provider
        self.selected_symbol_provider = selected_symbol_provider
        self.db_path_provider = db_path_provider
        self.preview_handler = preview_handler
        self.chart_focus_handler = chart_focus_handler
        self.load_symbol_handler = load_symbol_handler
        self.render_markers_handler = render_markers_handler
        self.add_to_watchlist = add_to_watchlist

        self.current_strategy_key: Optional[str] = None
        self.param_widgets: Dict[str, QtWidgets.QWidget] = {}
        self.scan_results: List[ScanResult] = []
        self.backtest_results: List[Dict[str, Any]] = []
        initial_symbol = self.selected_symbol_provider() if selected_symbol_provider else None
        self._current_selected_symbol: Optional[str] = initial_symbol
        self.latest_backtest_result: Optional[BacktestResult] = None
        base_dir = Path(__file__).resolve().parent.parent
        self.backtest_equity_template = base_dir / 'rendering' / 'templates' / 'backtest_equity.html'
        self._equity_dialog: Optional[EChartsPreviewDialog] = None

        # Faster scan defaults: larger并发。根据CPU动态提升线程数，力求更快扫描
        cpu_cnt = os.cpu_count() or 8
        # 更激进的并发，目标尽量压满 CPU（最高 512 线程）
        max_workers = min(512, max(8, cpu_cnt * 16))
        self.scanner = StrategyScanner(registry, batch_size=128, max_workers=max_workers, rows_per_symbol=800)
        self.scanner.progress.connect(self._append_scan_log)
        self.scanner.progress.connect(self._on_scan_progress)
        self.scanner.result.connect(self._on_scan_result)
        self.scanner.finished.connect(self._on_scan_finished)
        self.scanner.failed.connect(self._on_scan_failed)
        self.scanner.cancelled.connect(self._on_scan_cancelled)
        self.engine = BacktestEngine(registry)
        self.engine.progress.connect(self._append_backtest_log)
        self.engine.finished.connect(self._on_backtest_finished)
        self.engine.failed.connect(self._on_backtest_failed)
        self.engine.cancelled.connect(self._on_backtest_cancelled)

        self.scan_kpis: Dict[str, QtWidgets.QLabel] = {}
        self.backtest_kpis: Dict[str, QtWidgets.QLabel] = {}
        self.scan_running = False
        self.backtest_running = False
        self.scan_progress_label: Optional[QtWidgets.QLabel] = None
        self.scan_total_count = 0
        self.scan_processed_count = 0

        self._build_ui()
        self.refresh_strategy_items()
        self._apply_auto_universe_symbol()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel('策略研究工作台', self)
        title.setObjectName('WorkbenchTitle')
        title.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addWidget(title)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self.main_splitter.setObjectName('WorkbenchSplitter')
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self._build_card_panel())
        self.main_splitter.addWidget(self._build_result_tabs())
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([320, 960])
        layout.addWidget(self.main_splitter, 1)

    def _build_card_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame(self)
        frame.setObjectName('StrategyCardPanel')
        frame.setMinimumWidth(280)
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        frame_layout.setSpacing(8)

        header_layout = QtWidgets.QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        title_row = QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title = QtWidgets.QLabel('策略精选', frame)
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.card_filter = QtWidgets.QComboBox(frame)
        self.card_filter.addItems(['全部', '波动策略', '形态识别', '趋势跟踪'])
        self.card_filter.currentIndexChanged.connect(lambda _: self.refresh_strategy_items())
        title_row.addWidget(self.card_filter)
        header_layout.addLayout(title_row)

        self.card_search = QtWidgets.QLineEdit(frame)
        self.card_search.setPlaceholderText('搜索策略 / 关键词')
        self.card_search.setClearButtonEnabled(True)
        self.card_search.textChanged.connect(lambda _: self.refresh_strategy_items())
        header_layout.addWidget(self.card_search)
        frame_layout.addLayout(header_layout)

        self.card_view = QtWidgets.QListWidget(frame)
        self.card_view.setObjectName('StrategyCardList')
        self.card_view.setViewMode(QtWidgets.QListView.ListMode)
        self.card_view.setMovement(QtWidgets.QListView.Static)
        self.card_view.setSpacing(6)
        self.card_view.setUniformItemSizes(False)
        self.card_view.setWordWrap(True)
        self.card_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.card_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.card_view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.card_view.itemSelectionChanged.connect(self._on_card_selection_changed)
        frame_layout.addWidget(self.card_view, 1)
        return frame

    def _build_preview_tab(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame(self.result_tabs)
        panel.setObjectName('StrategyDetailPanel')
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.description_label = QtWidgets.QLabel('选择策略以查看描述', panel)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName('StrategyDescription')
        layout.addWidget(self.description_label)

        # 去掉多余标题，减少视觉干扰
        self.param_group = QtWidgets.QGroupBox('', panel)
        self.param_form = QtWidgets.QFormLayout()
        self.param_form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.param_group.setLayout(self.param_form)
        layout.addWidget(self.param_group)

        preview_box = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton('即时预览', panel)
        self.preview_button.setProperty('class', 'primary')
        self.preview_button.clicked.connect(self._run_preview)
        preview_box.addWidget(self.preview_button)
        self.preview_status = QtWidgets.QLabel('', panel)
        preview_box.addWidget(self.preview_status, 1)
        layout.addLayout(preview_box)
        layout.addStretch(1)
        return panel

    def _build_result_tabs(self) -> QtWidgets.QTabWidget:
        self.result_tabs = QtWidgets.QTabWidget(self)
        self.result_tabs.setObjectName('WorkbenchTabs')
        self.result_tabs.addTab(self._build_preview_tab(), '策略预览')
        self.result_tabs.addTab(self._build_scan_tab(), '策略选股')
        self.result_tabs.addTab(self._build_backtest_tab(), '策略回测')
        return self.result_tabs

    def _build_scan_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget(self)
        tab.setObjectName('ScanTab')
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        strip, labels = self._create_kpi_strip(['候选数', '平均得分', '最高得分'])
        self.scan_kpis = labels
        layout.addWidget(strip)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.scan_universe = QtWidgets.QLineEdit(tab)
        self.scan_universe.setPlaceholderText('留空使用全部股票')
        form.addRow('股票池:', self.scan_universe)

        self.scan_board_filter = QtWidgets.QListWidget(tab)
        self.scan_board_filter.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        for name in ['创业板', '科创板', '北交所', '新三板']:
            item = QtWidgets.QListWidgetItem(name)
            item.setCheckState(QtCore.Qt.Unchecked)
            self.scan_board_filter.addItem(item)
        form.addRow('板块过滤:', self.scan_board_filter)

        self.scan_start = QtWidgets.QDateEdit(tab)
        self.scan_start.setCalendarPopup(True)
        self.scan_start.setDate(QtCore.QDate.currentDate())
        form.addRow('开始日期:', self.scan_start)

        self.scan_end = QtWidgets.QDateEdit(tab)
        self.scan_end.setCalendarPopup(True)
        self.scan_end.setDate(QtCore.QDate.currentDate())
        form.addRow('结束日期:', self.scan_end)
        layout.addLayout(form)

        action_row = QtWidgets.QHBoxLayout()
        self.scan_button = QtWidgets.QPushButton('开始选股', tab)
        self.scan_button.setProperty('class', 'primary')
        self.scan_button.clicked.connect(self._run_scan)
        action_row.addWidget(self.scan_button)

        self.scan_cancel_button = QtWidgets.QPushButton('取消选股', tab)
        self.scan_cancel_button.setProperty('class', 'danger')
        self.scan_cancel_button.clicked.connect(self._cancel_scan)
        self.scan_cancel_button.setVisible(False)
        action_row.addWidget(self.scan_cancel_button)

        self.scan_add_watchlist_button = QtWidgets.QPushButton('加入自选', tab)
        self.scan_add_watchlist_button.setProperty('class', 'ghost')
        self.scan_add_watchlist_button.setEnabled(False)
        self.scan_add_watchlist_button.clicked.connect(self._add_selected_to_watchlist)
        action_row.addWidget(self.scan_add_watchlist_button)

        self.scan_progress_label = QtWidgets.QLabel('进度 0/0', tab)
        self.scan_progress_label.setProperty('class', 'muted')
        action_row.addWidget(self.scan_progress_label)
        action_row.addStretch(1)

        self.scan_export_button = QtWidgets.QPushButton('导出 CSV', tab)
        self.scan_export_button.setProperty('class', 'ghost')
        self.scan_export_button.setEnabled(False)
        self.scan_export_button.clicked.connect(self._export_scan_results)
        action_row.addWidget(self.scan_export_button)

        self.scan_export_image_button = QtWidgets.QPushButton('导出图片', tab)
        self.scan_export_image_button.setProperty('class', 'ghost')
        self.scan_export_image_button.setEnabled(False)
        self.scan_export_image_button.clicked.connect(self._export_scan_image)
        action_row.addWidget(self.scan_export_image_button)

        self.scan_copy_button = QtWidgets.QPushButton('复制代码', tab)
        self.scan_copy_button.setProperty('class', 'ghost')
        self.scan_copy_button.setEnabled(False)
        self.scan_copy_button.clicked.connect(self._copy_scan_symbols)
        action_row.addWidget(self.scan_copy_button)
        layout.addLayout(action_row)

        self.scan_table = QtWidgets.QTableWidget(tab)
        self.scan_table.setProperty('class', 'data-table')
        self.scan_table.setColumnCount(6)
        self.scan_table.setHorizontalHeaderLabels(['股票', '代码', '买入日期', '买入价', '得分', '备注'])
        self.scan_table.horizontalHeader().setStretchLastSection(True)
        self.scan_table.verticalHeader().setVisible(False)
        self.scan_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.scan_table.doubleClicked.connect(self._on_scan_row_activated)
        self.scan_table.itemSelectionChanged.connect(self._update_scan_action_state)
        layout.addWidget(self.scan_table, 1)

        self.scan_log = QtWidgets.QTextEdit(tab)
        self.scan_log.setObjectName('LogPanel')
        self.scan_log.setReadOnly(True)
        self.scan_log.setMaximumHeight(120)
        layout.addWidget(self.scan_log)
        return tab

    def _build_backtest_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget(self)
        tab.setObjectName('BacktestTab')
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        strip, labels = self._create_kpi_strip(['净利润', '总收益%', '最大回撤', '胜率'])
        self.backtest_kpis = labels
        layout.addWidget(strip)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.backtest_universe = QtWidgets.QLineEdit(tab)
        self.backtest_universe.setClearButtonEnabled(True)
        self.backtest_universe.textChanged.connect(lambda _: self._on_universe_text_changed(self.backtest_universe))
        self.backtest_universe.setPlaceholderText('留空使用全部股票')
        form.addRow('股票池:', self.backtest_universe)

        self.backtest_start = QtWidgets.QDateEdit(tab)
        self.backtest_start.setCalendarPopup(True)
        self.backtest_start.setDate(QtCore.QDate.currentDate().addYears(-2))
        form.addRow('开始日期:', self.backtest_start)

        self.backtest_end = QtWidgets.QDateEdit(tab)
        self.backtest_end.setCalendarPopup(True)
        self.backtest_end.setDate(QtCore.QDate.currentDate())
        form.addRow('结束日期:', self.backtest_end)

        self.backtest_cash = QtWidgets.QDoubleSpinBox(tab)
        self.backtest_cash.setRange(10_000, 100_000_000)
        self.backtest_cash.setSingleStep(100_000)
        self.backtest_cash.setValue(1_000_000)
        form.addRow('初始资金:', self.backtest_cash)

        self.backtest_max_positions = QtWidgets.QSpinBox(tab)
        self.backtest_max_positions.setRange(1, 50)
        self.backtest_max_positions.setValue(5)
        form.addRow('最大持仓数:', self.backtest_max_positions)

        self.backtest_position_pct = QtWidgets.QDoubleSpinBox(tab)
        self.backtest_position_pct.setRange(1.0, 100.0)
        self.backtest_position_pct.setDecimals(1)
        self.backtest_position_pct.setSingleStep(5.0)
        self.backtest_position_pct.setSuffix('%')
        self.backtest_position_pct.setValue(20.0)
        form.addRow('单笔仓位:', self.backtest_position_pct)

        self.backtest_commission = QtWidgets.QDoubleSpinBox(tab)
        self.backtest_commission.setRange(0.0, 1.0)
        self.backtest_commission.setDecimals(3)
        self.backtest_commission.setSingleStep(0.01)
        self.backtest_commission.setSuffix('%')
        self.backtest_commission.setValue(0.03)
        form.addRow('佣金费率:', self.backtest_commission)

        self.backtest_slippage = QtWidgets.QDoubleSpinBox(tab)
        self.backtest_slippage.setRange(0.0, 1.0)
        self.backtest_slippage.setDecimals(3)
        self.backtest_slippage.setSingleStep(0.01)
        self.backtest_slippage.setSuffix('%')
        self.backtest_slippage.setValue(0.05)
        form.addRow('滑点假设:', self.backtest_slippage)
        layout.addLayout(form)

        action_row = QtWidgets.QHBoxLayout()
        self.backtest_button = QtWidgets.QPushButton('运行回测', tab)
        self.backtest_button.setProperty('class', 'primary')
        self.backtest_button.clicked.connect(self._run_backtest)
        action_row.addWidget(self.backtest_button)
        self.backtest_cancel_button = QtWidgets.QPushButton('取消回测', tab)
        self.backtest_cancel_button.setProperty('class', 'danger')
        self.backtest_cancel_button.clicked.connect(self._cancel_backtest)
        self.backtest_cancel_button.setVisible(False)
        action_row.addWidget(self.backtest_cancel_button)
        self.backtest_equity_button = QtWidgets.QPushButton('查看收益曲线', tab)
        self.backtest_equity_button.setProperty('class', 'ghost')
        self.backtest_equity_button.setEnabled(False)
        self.backtest_equity_button.clicked.connect(self._show_equity_curve)
        action_row.addWidget(self.backtest_equity_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.backtest_table = QtWidgets.QTableWidget(tab)
        self.backtest_table.setProperty('class', 'data-table')
        self.backtest_table.setColumnCount(8)
        self.backtest_table.setHorizontalHeaderLabels([
            '股票', '买入日', '卖出日', '仓位(股)', '买入价', '卖出价', '收益%', '收益额',
        ])
        self.backtest_table.verticalHeader().setVisible(False)
        self.backtest_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.backtest_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.backtest_table.setAlternatingRowColors(True)
        header = self.backtest_table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.backtest_table.doubleClicked.connect(self._on_backtest_row_activated)
        layout.addWidget(self.backtest_table, 1)

        self.backtest_log = QtWidgets.QTextEdit(tab)
        self.backtest_log.setObjectName('LogPanel')
        self.backtest_log.setReadOnly(True)
        self.backtest_log.setMaximumHeight(200)
        layout.addWidget(self.backtest_log)
        return tab

    def _create_kpi_strip(self, names: List[str]) -> Tuple[QtWidgets.QWidget, Dict[str, QtWidgets.QLabel]]:
        wrapper = QtWidgets.QFrame(self)
        wrapper.setObjectName('KpiStrip')
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        labels: Dict[str, QtWidgets.QLabel] = {}
        for name in names:
            card = QtWidgets.QFrame(wrapper)
            card.setObjectName('KpiCard')
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(12, 8, 12, 8)
            card_layout.setSpacing(2)
            title = QtWidgets.QLabel(name, card)
            title.setObjectName('KpiTitle')
            value = QtWidgets.QLabel('--', card)
            value.setObjectName('KpiValue')
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            layout.addWidget(card)
            labels[name] = value
        layout.addStretch(1)
        return wrapper, labels

    # ------------------------------------------------------------------
    def refresh_strategy_items(self) -> None:
        definitions = self.registry.all()
        self.card_view.blockSignals(True)
        self.card_view.clear()
        filter_text = self.card_filter.currentText() if hasattr(self, 'card_filter') else '全部'
        search_text = self.card_search.text().strip().lower() if hasattr(self, 'card_search') else ''

        for definition in definitions:
            if filter_text != '全部' and filter_text not in definition.tags:
                continue
            haystack = ' '.join(filter(None, [definition.title, definition.description, ' '.join(definition.tags)])).lower()
            if search_text and search_text not in haystack:
                continue
            snippet = (definition.description or '').replace('\n', ' ').strip()
            if len(snippet) > 48:
                snippet = snippet[:45] + '…'
            meta = ' / '.join(definition.tags[:3])
            secondary = meta or snippet
            if not secondary:
                secondary = '--'
            display_text = f"{definition.title}\n{secondary}"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, definition.key)
            item.setToolTip(definition.description or '')
            item.setIcon(self._build_strategy_icon(definition))
            item.setSizeHint(QtCore.QSize(260, 68))
            self.card_view.addItem(item)

        self.card_view.blockSignals(False)
        if self.card_view.count():
            self.card_view.setCurrentRow(0)
        else:
            self._set_current_strategy(None)

    def _build_strategy_icon(self, definition: StrategyDefinition) -> QtGui.QIcon:
        colors = ['#1f5eff', '#0bbadf', '#64c5b1', '#ff915c', '#8c7bff']
        color = colors[hash(definition.key) % len(colors)]
        pix = QtGui.QPixmap(72, 72)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(color)))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(QtCore.QRectF(4, 4, 64, 64), 12, 12)
        painter.setPen(QtGui.QPen(QtGui.QColor('#111')))
        painter.setFont(QtGui.QFont('Segoe UI', 18, QtGui.QFont.Bold))
        painter.drawText(pix.rect(), QtCore.Qt.AlignCenter, definition.title[:1].upper())
        painter.end()
        return QtGui.QIcon(pix)

    def _on_card_selection_changed(self) -> None:
        row = self.card_view.currentRow()
        if row < 0:
            return
        item = self.card_view.item(row)
        key = item.data(QtCore.Qt.UserRole)
        self._set_current_strategy(str(key))

    def _set_current_strategy(self, key: Optional[str]) -> None:
        self.current_strategy_key = key
        definition = self._current_definition()
        if not definition:
            self.description_label.setText('暂无策略可用')
            self._rebuild_param_form(None)
            return
        self.description_label.setText(definition.description or '暂无描述')
        self._rebuild_param_form(definition)

    def _current_definition(self) -> Optional[StrategyDefinition]:
        if not self.current_strategy_key:
            return None
        return self.registry.get(self.current_strategy_key)

    def _rebuild_param_form(self, definition: Optional[StrategyDefinition]) -> None:
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        self.param_widgets.clear()

        if not definition or not definition.parameters:
            self.param_form.addRow(QtWidgets.QLabel('该策略暂无可配置参数', self))
            return

        for param in definition.parameters:
            widget: QtWidgets.QWidget
            if param.type == 'number':
                spin = QtWidgets.QDoubleSpinBox(self)
                spin.setRange(-1_000_000, 1_000_000)
                spin.setDecimals(4)
                spin.setValue(float(param.default or 0.0))
                widget = spin
            elif param.type == 'select' and param.options:
                combo = QtWidgets.QComboBox(self)
                for option in param.options:
                    combo.addItem(str(option), option)
                widget = combo
            else:
                edit = QtWidgets.QLineEdit(self)
                if param.default is not None:
                    edit.setText(str(param.default))
                widget = edit

            helper = param.description or ''
            row_label = QtWidgets.QLabel(param.label, self)
            if helper:
                row_label.setToolTip(helper)
                widget.setToolTip(helper)
            self.param_form.addRow(row_label, widget)
            self.param_widgets[param.key] = widget

    def _collect_params(self) -> Dict[str, object]:
        result: Dict[str, object] = {}
        definition = self._current_definition()
        if not definition or not definition.parameters:
            return result
        for param in definition.parameters:
            widget = self.param_widgets.get(param.key)
            if widget is None:
                continue
            value: object
            if isinstance(widget, QtWidgets.QDoubleSpinBox):
                value = widget.value()
            elif isinstance(widget, QtWidgets.QComboBox):
                value = widget.currentData()
            else:
                value = widget.text()
            result[param.key] = value
        return result

    # ------------------------------------------------------------------
    def _resolve_universe(self, text_field: QtWidgets.QLineEdit, *, prefer_selected: bool = False) -> List[str]:
        raw = text_field.text().strip()
        if raw:
            return [token.strip() for token in raw.split(',') if token.strip()]

        auto_value = text_field.property('autoFilledValue')
        if isinstance(auto_value, str) and auto_value:
            return [auto_value]

        try:
            universe = list(self.universe_provider() or [])
        except Exception:
            universe = []
        if universe:
            return universe

        if prefer_selected and self.selected_symbol_provider:
            selected = self.selected_symbol_provider()
            if selected:
                return [selected]

        return []

    def _run_preview(self) -> None:
        definition = self._current_definition()
        if not definition:
            QtWidgets.QMessageBox.warning(self, '策略缺失', '请选择策略')
            return
        # 预览前先清空旧标记，避免策略切换后残留显示
        try:
            self.render_markers_handler and self.render_markers_handler('', [], [])
        except Exception:
            pass
        params = self._collect_params()
        try:
            result = self.preview_handler(definition.key, params)
        except Exception as exc:  # pragma: no cover
            message = str(exc)
            # 在状态栏显示完整错误，便于复制；同时尝试写入剪贴板
            self.preview_status.setText(f"预览失败: {message}")
            try:
                QtWidgets.QApplication.clipboard().setText(message)
            except Exception:
                pass
            QtWidgets.QMessageBox.critical(self, '策略运行失败', f"{message}\n\n已写入状态栏，可直接复制。")
            return
        if result:
            self.preview_status.setText(result.status_message or '已生成标记')
            self.chart_focus_handler()
        else:
            # 没有结果时也刷新一次空图，确保界面清空
            try:
                self.render_markers_handler and self.render_markers_handler('', [], [])
            except Exception:
                pass
            self.preview_status.setText('未生成标记')

    def _run_scan(self) -> None:
        definition = self._current_definition()
        if not definition:
            QtWidgets.QMessageBox.warning(self, '策略缺失', '请选择策略')
            return
        universe = self._resolve_universe(self.scan_universe)
        universe = self._filter_universe_by_board(universe)
        if not universe:
            QtWidgets.QMessageBox.warning(self, '股票池为空', '请先加载股票列表')
            return
        db_path = self.db_path_provider()
        if not db_path or not Path(db_path).exists():
            QtWidgets.QMessageBox.warning(self, '缺少数据库', '请先选择数据库文件')
            return

        self.scan_total_count = len(universe)
        self.scan_processed_count = 0
        self.scan_results = []
        self.scan_table.setRowCount(0)
        self._update_scan_progress_label()
        request = ScanRequest(
            strategy_key=definition.key,
            universe=universe,
            start_date=self.scan_start.date().toPyDate(),
            end_date=self.scan_end.date().toPyDate(),
            params=self._collect_params(),
        )
        self.scan_log.append('开始选股...')
        self._toggle_scan_controls(True)
        try:
            self.scanner.run_async(request, db_path)
        except Exception as exc:  # pragma: no cover
            self._toggle_scan_controls(False)
            QtWidgets.QMessageBox.critical(self, '扫描启动失败', str(exc))

    def _cancel_scan(self) -> None:
        if not self.scan_running:
            return
        self.scan_log.append('正在取消选股...')
        self.scanner.cancel_async()

    def _populate_scan_results(self, results: List[ScanResult]) -> None:
        self.scan_results = results
        self.scan_table.setRowCount(len(results))
        for row, result in enumerate(results):
            display_name = result.name or result.symbol
            self.scan_table.setItem(row, 0, QtWidgets.QTableWidgetItem(display_name))
            self.scan_table.setItem(row, 1, QtWidgets.QTableWidgetItem(result.symbol))
            self.scan_table.setItem(row, 2, QtWidgets.QTableWidgetItem(result.entry_date or ''))
            price_text = f"{result.entry_price:.2f}" if isinstance(result.entry_price, (int, float)) else ''
            self.scan_table.setItem(row, 3, QtWidgets.QTableWidgetItem(price_text))
            score_text = f"{result.score:.2f}" if isinstance(result.score, (int, float)) else str(result.score)
            self.scan_table.setItem(row, 4, QtWidgets.QTableWidgetItem(score_text))
            remark = result.metadata.get('note') or result.metadata.get('status', '')
            self.scan_table.setItem(row, 5, QtWidgets.QTableWidgetItem(remark))
        self.scan_log.append(f'选股完成，共 {len(results)} 条结果')
        self._update_scan_kpis(results)
        self._update_scan_action_state()

    def _append_scan_result_row(self, result: ScanResult) -> None:
        row = self.scan_table.rowCount()
        self.scan_table.insertRow(row)
        display_name = result.name or result.symbol
        self.scan_table.setItem(row, 0, QtWidgets.QTableWidgetItem(display_name))
        self.scan_table.setItem(row, 1, QtWidgets.QTableWidgetItem(result.symbol))
        self.scan_table.setItem(row, 2, QtWidgets.QTableWidgetItem(result.entry_date or ''))
        price_text = f"{result.entry_price:.2f}" if isinstance(result.entry_price, (int, float)) else ''
        self.scan_table.setItem(row, 3, QtWidgets.QTableWidgetItem(price_text))
        score_text = f"{result.score:.2f}" if isinstance(result.score, (int, float)) else str(result.score)
        self.scan_table.setItem(row, 4, QtWidgets.QTableWidgetItem(score_text))
        remark = result.metadata.get('note') or result.metadata.get('status', '')
        self.scan_table.setItem(row, 5, QtWidgets.QTableWidgetItem(remark))

    def _on_scan_result(self, result: object) -> None:
        if not isinstance(result, ScanResult):
            return
        self.scan_results.append(result)
        self._append_scan_result_row(result)
        self._update_scan_kpis(self.scan_results)
        self._update_scan_action_state()

    def _populate_backtest_table(self, trades: List[Dict[str, Any]]) -> None:
        self.backtest_results = trades
        self.backtest_table.setRowCount(len(trades))
        for row, trade in enumerate(trades):
            symbol_item = QtWidgets.QTableWidgetItem(str(trade.get('symbol', '')))
            entry_date_item = QtWidgets.QTableWidgetItem(str(trade.get('entry_date', '')))
            exit_date_item = QtWidgets.QTableWidgetItem(str(trade.get('exit_date', '')))
            shares_value = trade.get('shares', 0.0)
            shares_item = QtWidgets.QTableWidgetItem(f"{shares_value:.2f}")
            entry_price = trade.get('entry_price')
            exit_price = trade.get('exit_price')
            entry_price_item = QtWidgets.QTableWidgetItem(f"{entry_price:.2f}" if isinstance(entry_price, (int, float)) else '')
            exit_price_item = QtWidgets.QTableWidgetItem(f"{exit_price:.2f}" if isinstance(exit_price, (int, float)) else '')
            return_pct = trade.get('return_pct')
            return_item = QtWidgets.QTableWidgetItem(f"{(return_pct or 0) * 100:.2f}%")
            pnl = trade.get('pnl') or 0.0
            pnl_item = QtWidgets.QTableWidgetItem(f"{pnl:.2f}")
            color_positive = QtGui.QColor('#ef4444')
            color_negative = QtGui.QColor('#16a34a')
            if pnl_item and isinstance(pnl, (int, float)):
                pnl_item.setForeground(QtGui.QBrush(color_positive if pnl >= 0 else color_negative))
            if return_item and isinstance(return_pct, (int, float)):
                return_item.setForeground(QtGui.QBrush(color_positive if return_pct >= 0 else color_negative))

            self.backtest_table.setItem(row, 0, symbol_item)
            self.backtest_table.setItem(row, 1, entry_date_item)
            self.backtest_table.setItem(row, 2, exit_date_item)
            self.backtest_table.setItem(row, 3, shares_item)
            self.backtest_table.setItem(row, 4, entry_price_item)
            self.backtest_table.setItem(row, 5, exit_price_item)
            self.backtest_table.setItem(row, 6, return_item)
            self.backtest_table.setItem(row, 7, pnl_item)

    def _on_backtest_row_activated(self, index: QtCore.QModelIndex) -> None:
        row = index.row()
        if not (0 <= row < len(self.backtest_results)):
            return
        trade = self.backtest_results[row]
        symbol = str(trade.get('symbol') or '').strip()
        if not symbol:
            return
        try:
            self.load_symbol_handler(symbol)
        except Exception:
            pass
        markers: List[Dict[str, Any]] = []
        entry_date = trade.get('entry_date') or trade.get('entryTime')
        exit_date = trade.get('exit_date') or trade.get('exitTime')
        entry_price = trade.get('entry_price')
        exit_price = trade.get('exit_price')
        if entry_date:
            markers.append({
                'id': f'bt_entry_{row}',
                'time': entry_date,
                'position': 'belowBar',
                'color': '#10b981',
                'shape': 'triangle',
                'text': f'回测买入 {entry_price:.2f}' if isinstance(entry_price, (int, float)) else '回测买入',
                'price': entry_price,
            })
        if exit_date:
            markers.append({
                'id': f'bt_exit_{row}',
                'time': exit_date,
                'position': 'aboveBar',
                'color': '#ef4444',
                'shape': 'triangle',
                'text': f'回测卖出 {exit_price:.2f}' if isinstance(exit_price, (int, float)) else '回测卖出',
                'price': exit_price,
            })
        if self.render_markers_handler:
            try:
                self.render_markers_handler(symbol, markers, [])
            except Exception:
                pass
        if self.chart_focus_handler:
            try:
                self.chart_focus_handler()
            except Exception:
                pass

    def update_selected_symbol(self, symbol: Optional[str]) -> None:
        self._current_selected_symbol = symbol
        self._apply_auto_universe_symbol()

    def _apply_auto_universe_symbol(self) -> None:
        if not hasattr(self, 'backtest_universe'):
            return
        auto_flag = bool(self.backtest_universe.property('autoFilledValue'))
        current_text = self.backtest_universe.text().strip()
        if current_text and not auto_flag:
            return
        self._set_universe_field(self.backtest_universe, self._current_selected_symbol)

    def _set_universe_field(self, field: QtWidgets.QLineEdit, symbol: Optional[str]) -> None:
        field.blockSignals(True)
        field.setText(symbol or '')
        field.blockSignals(False)
        field.setProperty('autoFilledValue', symbol or '')

    def _on_universe_text_changed(self, field: QtWidgets.QLineEdit) -> None:
        field.setProperty('autoFilledValue', '')


    def _ensure_equity_dialog(self) -> EChartsPreviewDialog:
        if self._equity_dialog is None:
            if not self.backtest_equity_template.exists():
                raise RuntimeError(f'缺少模板文件: {self.backtest_equity_template}')
            self._equity_dialog = EChartsPreviewDialog(self.backtest_equity_template, self)
        return self._equity_dialog

    def _show_equity_curve(self) -> None:
        if not self.latest_backtest_result:
            QtWidgets.QMessageBox.information(self, '暂无数据', '请先运行一次回测。')
            return
        title = f"收益曲线 · {self.latest_backtest_result.strategy_key}"
        try:
            html = render_backtest_equity(
                self.latest_backtest_result.equity_curve,
                trades=self.latest_backtest_result.trades,
                metrics=self.latest_backtest_result.metrics,
                title=title,
            )
            dialog = self._ensure_equity_dialog()
        except Exception as exc:  # pragma: no cover - runtime errors
            QtWidgets.QMessageBox.critical(self, '渲染失败', str(exc))
            return
        dialog.show_html(title, html)

    def _update_scan_kpis(self, results: List[ScanResult]) -> None:
        total = len(results)
        avg_score = sum(r.score for r in results) / total if total else 0.0
        best = max((r.score for r in results), default=0.0)
        self._assign_kpi_values(self.scan_kpis, {
            '候选数': f'{total}',
            '平均得分': f'{avg_score:.2f}',
            '最高得分': f'{best:.2f}',
        })

    def _on_scan_row_activated(self, index: QtCore.QModelIndex) -> None:
        row = index.row()
        if 0 <= row < len(self.scan_results):
            table_name = self.scan_results[row].table_name
            self.load_symbol_handler(table_name)
            # 延迟触发预览，确保K线已切换到选中标的
            QtCore.QTimer.singleShot(80, self._preview_current_strategy)

    def _append_scan_log(self, message: str) -> None:
        self.scan_log.append(message)

    def _on_scan_progress(self, message: str) -> None:
        match = re.search(r"\((\d+)/(\d+)\)", message)
        if match:
            try:
                self.scan_processed_count = int(match.group(1))
                self.scan_total_count = int(match.group(2))
                self._update_scan_progress_label()
            except ValueError:
                pass

    def _on_scan_finished(self, results: object) -> None:
        parsed = list(results or [])
        self.scan_processed_count = self.scan_total_count or len(parsed)
        self._populate_scan_results(parsed)
        self._toggle_scan_controls(False)

    def _on_scan_failed(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, '选股失败', message)
        self._toggle_scan_controls(False)

    def _on_scan_cancelled(self) -> None:
        self.scan_log.append('选股已取消')
        self._toggle_scan_controls(False)

    def _toggle_scan_controls(self, running: bool) -> None:
        self.scan_running = running
        self.scan_button.setEnabled(not running)
        self.scan_cancel_button.setVisible(running)
        self.scan_cancel_button.setEnabled(running)
        self._update_scan_action_state()
        if not running and self.scan_total_count:
            self.scan_processed_count = min(self.scan_processed_count, self.scan_total_count)
            self._update_scan_progress_label()

    def _preview_current_strategy(self) -> None:
        if not self.preview_handler:
            return
        definition = self._current_definition()
        if not definition:
            return
        params = self._collect_params()
        try:
            self.preview_handler(definition.key, params)
        except Exception as exc:  # pragma: no cover - runtime diagnostics
            self.scan_log.append(f'预览失败: {exc}')

    def _filter_universe_by_board(self, universe: List[str]) -> List[str]:
        if not hasattr(self, 'scan_board_filter'):
            return universe
        # 勾选的板块视为要过滤掉的板块
        selected_boards = [
            item.text()
            for item in self.scan_board_filter.findItems('*', QtCore.Qt.MatchWrap | QtCore.Qt.MatchWildcard)
            if item.checkState() == QtCore.Qt.Checked
        ]
        if not selected_boards:
            return universe
        filtered: List[str] = []
        for code in universe:
            # 若代码属于勾选板块，则跳过；未命中勾选板块的保留
            if any(self._matches_board(code, board) for board in selected_boards):
                continue
            filtered.append(code)
        return filtered

    @staticmethod
    def _matches_board(code: str, board: str) -> bool:
        code_str = (code or "").strip()
        if not code_str:
            return False
        # 取纯数字部分开头判断
        digits = "".join(ch for ch in code_str if ch.isdigit())
        prefix = digits[:3] if len(digits) >= 3 else digits

        if board == "创业板":
            return prefix.startswith("300") or prefix.startswith("301")
        if board == "科创板":
            return prefix.startswith("688") or prefix.startswith("689")
        if board == "北交所":
            return prefix.startswith("8") or prefix.startswith("4") or prefix.startswith("920")
        if board == "新三板":
            return prefix.startswith("43") or prefix.startswith("83") or prefix.startswith("87")
        return False

    def _update_scan_progress_label(self) -> None:
        if self.scan_progress_label is None:
            return
        total = max(self.scan_total_count, 0)
        processed = min(self.scan_processed_count, total) if total else self.scan_processed_count
        self.scan_progress_label.setText(f'进度 {processed}/{total}')

    def _update_scan_action_state(self) -> None:
        has_results = bool(self.scan_results)
        enabled = has_results and not self.scan_running
        self.scan_export_button.setEnabled(enabled)
        if hasattr(self, 'scan_export_image_button'):
            self.scan_export_image_button.setEnabled(enabled)
        self.scan_copy_button.setEnabled(enabled)
        has_selection = bool(self.scan_table.selectedItems()) if hasattr(self, 'scan_table') else False
        if hasattr(self, 'scan_add_watchlist_button'):
            self.scan_add_watchlist_button.setEnabled(
                enabled and has_selection and self.add_to_watchlist is not None
            )

    def _export_scan_results(self) -> None:
        if not self.scan_results:
            QtWidgets.QMessageBox.information(self, '无数据', '当前没有可导出的选股结果。')
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            '导出策略选股结果',
            'strategy_picks.csv',
            'CSV 文件 (*.csv)'
        )
        if not file_path:
            return
        try:
            with open(file_path, 'w', encoding='utf-8-sig', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(['排名', '股票', '买入日期', '买入价', '得分', '备注'])
                for idx, result in enumerate(self.scan_results, start=1):
                    price = f"{result.entry_price:.2f}" if isinstance(result.entry_price, (int, float)) else ''
                    remark = result.metadata.get('note') or result.metadata.get('status', '')
                    writer.writerow([
                        idx,
                        result.symbol,
                        result.entry_date or '',
                        price,
                        result.score,
                        remark,
                    ])
        except Exception as exc:  # pragma: no cover - file errors
            QtWidgets.QMessageBox.critical(self, '导出失败', str(exc))
            return
        self.scan_log.append(f'已导出到 {file_path}')

    def _copy_scan_symbols(self) -> None:
        if not self.scan_results:
            QtWidgets.QMessageBox.information(self, '无数据', '当前没有可复制的选股结果。')
            return
        symbols = [result.symbol for result in self.scan_results]
        QtWidgets.QApplication.clipboard().setText('\n'.join(symbols))
        self.scan_log.append('已复制选股结果到剪贴板')

    def _export_scan_image(self) -> None:
        if not self.scan_results:
            QtWidgets.QMessageBox.information(self, '无数据', '当前没有可导出的选股结果。')
            return

        default_path = Path.home() / 'Desktop' / 'strategy_picks.png'
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            '导出选股结果图片',
            str(default_path),
            'PNG 图片 (*.png)'
        )
        if not file_path:
            return

        cols = 4
        cell_w = 260
        cell_h = 90
        gap = 14
        margin = 16
        rows = math.ceil(len(self.scan_results) / cols)
        width = margin * 2 + cols * cell_w + (cols - 1) * gap
        height = margin * 2 + rows * cell_h + (rows - 1) * gap

        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtGui.QColor('#f8fafc'))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        title_font = QtGui.QFont()
        title_font.setWeight(QtGui.QFont.DemiBold)
        title_font.setPointSize(title_font.pointSize() + 1)
        meta_font = QtGui.QFont()
        meta_font.setPointSize(meta_font.pointSize() - 1)

        for idx, result in enumerate(self.scan_results):
            col = idx % cols
            row = idx // cols
            x = margin + col * (cell_w + gap)
            y = margin + row * (cell_h + gap)
            rect = QtCore.QRectF(x, y, cell_w, cell_h)

            painter.setPen(QtGui.QPen(QtGui.QColor('#e2e8f0')))
            painter.setBrush(QtGui.QColor('#ffffff'))
            painter.drawRoundedRect(rect, 8, 8)

            # Text content
            symbol = str(result.symbol or result.table_name or '').strip()
            name = str(result.name or '').strip()
            header = f"{symbol}  {name}" if name else symbol
            score = f"得分 {result.score:.2f}" if isinstance(result.score, (int, float)) else f"得分 {result.score}"
            entry_date = f"买入日: {result.entry_date or '--'}"
            price_val = ''
            if isinstance(result.entry_price, (int, float)):
                price_val = f"买入价: {result.entry_price:.2f}"
            elif result.entry_price:
                price_val = f"买入价: {result.entry_price}"

            painter.setFont(title_font)
            painter.setPen(QtGui.QColor('#0f172a'))
            painter.drawText(rect.adjusted(12, 10, -12, -10), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, header)

            painter.setFont(meta_font)
            painter.setPen(QtGui.QColor('#475569'))
            painter.drawText(rect.adjusted(12, 36, -12, -10), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, entry_date)
            painter.drawText(rect.adjusted(12, 56, -12, -10), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, price_val)
            painter.drawText(rect.adjusted(12, 10, -12, -10), QtCore.Qt.AlignRight | QtCore.Qt.AlignTop, score)

        painter.end()

        saved = pixmap.save(file_path, 'PNG')
        if not saved:
            QtWidgets.QMessageBox.warning(self, '导出失败', '无法保存图片，请检查路径或权限。')
            return
        self.scan_log.append(f'已导出图片到 {file_path}')
        QtWidgets.QMessageBox.information(self, '导出完成', f'图片已保存到:\n{file_path}')

    def _add_selected_to_watchlist(self) -> None:
        if self.add_to_watchlist is None:
            QtWidgets.QMessageBox.information(self, '未启用自选', '未检测到自选股存储，无法加入自选。')
            return
        if not hasattr(self, 'scan_table') or self.scan_table is None:
            return
        rows = {idx.row() for idx in self.scan_table.selectedIndexes()}
        if not rows:
            QtWidgets.QMessageBox.information(self, '无选中', '请先在列表中选择要加入自选的股票。')
            return
        items: List[Tuple[str, str]] = []
        for row in rows:
            code_item = self.scan_table.item(row, 1)
            name_item = self.scan_table.item(row, 0)
            symbol = code_item.text().strip() if code_item else ''
            name = name_item.text().strip() if name_item else ''
            if symbol:
                items.append((symbol, name))
        if not items:
            QtWidgets.QMessageBox.information(self, '无有效数据', '所选行缺少代码，无法加入自选。')
            return
        self.add_to_watchlist(items)
        self.scan_log.append(f'已将 {len(items)} 只股票加入自选')

    def _toggle_backtest_controls(self, running: bool) -> None:
        self.backtest_running = running
        if hasattr(self, 'backtest_button'):
            self.backtest_button.setEnabled(not running)
        if hasattr(self, 'backtest_cancel_button'):
            self.backtest_cancel_button.setVisible(running)
            self.backtest_cancel_button.setEnabled(running)
        if hasattr(self, 'backtest_equity_button'):
            can_show = bool(self.latest_backtest_result) and not running
            self.backtest_equity_button.setEnabled(can_show)

    def _run_backtest(self) -> None:
        definition = self._current_definition()
        if not definition:
            QtWidgets.QMessageBox.warning(self, '策略缺失', '请选择策略')
            return
        universe = self._resolve_universe(self.backtest_universe, prefer_selected=True)
        if not universe:
            QtWidgets.QMessageBox.warning(self, '股票池为空', '请先加载股票列表')
            return
        db_path = self.db_path_provider()
        if not db_path or not Path(db_path).exists():
            QtWidgets.QMessageBox.warning(self, '缺少数据库', '请先选择数据库文件')
            return

        request = BacktestRequest(
            strategy_key=definition.key,
            universe=universe,
            start_date=self.backtest_start.date().toPyDate(),
            end_date=self.backtest_end.date().toPyDate(),
            initial_cash=float(self.backtest_cash.value()),
            params=self._collect_params(),
            max_positions=int(self.backtest_max_positions.value()),
            position_pct=float(self.backtest_position_pct.value()) / 100.0,
            commission_rate=float(self.backtest_commission.value()) / 100.0,
            slippage=float(self.backtest_slippage.value()) / 100.0,
        )
        self.latest_backtest_result = None
        self.backtest_log.append('开始回测...')
        self.backtest_table.setRowCount(0)
        self._toggle_backtest_controls(True)
        try:
            self.engine.run_async(request, db_path)
        except Exception as exc:  # pragma: no cover - unexpected failures
            self._toggle_backtest_controls(False)
            QtWidgets.QMessageBox.critical(self, '回测失败', str(exc))

    def _cancel_backtest(self) -> None:
        if not self.backtest_running:
            return
        self.backtest_log.append('正在取消回测...')
        self.engine.cancel_async()

    def _append_backtest_log(self, message: str) -> None:
        self.backtest_log.append(message)

    def _on_backtest_finished(self, result: BacktestResult) -> None:
        self.latest_backtest_result = result
        self._toggle_backtest_controls(False)
        self.backtest_log.append('回测完成')
        self.backtest_log.append(result.notes or str(result.metrics))
        self.backtest_log.append('---')
        self._populate_backtest_table(result.trades)
        self._update_backtest_kpis(result)

    def _update_backtest_kpis(self, result: BacktestResult) -> None:
        net = result.metrics.get('net_profit', 0.0)
        drawdown = result.metrics.get('max_drawdown', 0.0)
        win_rate = result.metrics.get('win_rate')
        if win_rate is None:
            trades = result.trades
            wins = sum(1 for trade in trades if trade.get('pnl', 0) > 0)
            win_rate = wins / len(trades) if trades else 0.0
        ret_pct = result.metrics.get('return_pct', 0.0)
        self._assign_kpi_values(self.backtest_kpis, {
            '净利润': f'{net:.2f}',
            '总收益%': f'{ret_pct:.2f}%',
            '最大回撤': f'{drawdown:.2f}',
            '胜率': f'{win_rate * 100:.1f}%',
        })

    def _assign_kpi_values(self, kpis: Dict[str, QtWidgets.QLabel], values: Dict[str, str]) -> None:
        for key, widget in kpis.items():
            widget.setText(values.get(key, '--'))

    def _on_backtest_failed(self, message: str) -> None:
        self._toggle_backtest_controls(False)
        QtWidgets.QMessageBox.critical(self, '回测失败', message)

    def _on_backtest_cancelled(self) -> None:
        self._toggle_backtest_controls(False)
        self.backtest_log.append('回测已取消')
