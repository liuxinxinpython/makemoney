from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]

from ..research import (
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


class StrategyWorkbenchPanel(QtWidgets.QWidget):
    '''Strategy research workbench inspired by professional terminals.'''

    def __init__(
        self,
        registry: StrategyRegistry,
        universe_provider: Callable[[], List[str]],
        db_path_provider: Callable[[], Path],
        preview_handler: Callable[[str, Dict[str, object]], Optional[StrategyRunResult]],
        chart_focus_handler: Callable[[], None],
        load_symbol_handler: Callable[[str], None],
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.universe_provider = universe_provider
        self.db_path_provider = db_path_provider
        self.preview_handler = preview_handler
        self.chart_focus_handler = chart_focus_handler
        self.load_symbol_handler = load_symbol_handler

        self.current_strategy_key: Optional[str] = None
        self.param_widgets: Dict[str, QtWidgets.QWidget] = {}
        self.scan_results: List[ScanResult] = []

        self.scanner = StrategyScanner(registry)
        self.scanner.progress.connect(self._append_scan_log)
        self.engine = BacktestEngine(registry)
        self.engine.progress.connect(self._append_backtest_log)
        self.engine.finished.connect(self._on_backtest_finished)
        self.engine.failed.connect(self._on_backtest_failed)

        self.scan_kpis: Dict[str, QtWidgets.QLabel] = {}
        self.backtest_kpis: Dict[str, QtWidgets.QLabel] = {}

        self._build_ui()
        self.refresh_strategy_items()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel('策略研究工作台', self)
        title.setObjectName('WorkbenchTitle')
        title.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addWidget(title)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical, self)
        self.main_splitter.setObjectName('WorkbenchSplitter')
        self.main_splitter.addWidget(self._build_card_panel())
        self.main_splitter.addWidget(self._build_detail_splitter())
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.main_splitter, 1)

    def _build_card_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame(self)
        frame.setObjectName('StrategyCardPanel')
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(6)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(QtWidgets.QLabel('精选策略', frame))
        header_layout.addStretch(1)
        self.card_filter = QtWidgets.QComboBox(frame)
        self.card_filter.addItems(['全部', '波动策略', '形态识别', '趋势跟踪'])
        self.card_filter.currentIndexChanged.connect(lambda _: self.refresh_strategy_items())
        header_layout.addWidget(self.card_filter)
        frame_layout.addLayout(header_layout)

        self.card_view = QtWidgets.QListWidget(frame)
        self.card_view.setViewMode(QtWidgets.QListView.IconMode)
        self.card_view.setMovement(QtWidgets.QListView.Static)
        self.card_view.setResizeMode(QtWidgets.QListView.Adjust)
        self.card_view.setIconSize(QtCore.QSize(64, 64))
        self.card_view.setGridSize(QtCore.QSize(180, 150))
        self.card_view.setSpacing(12)
        self.card_view.setWordWrap(True)
        self.card_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.card_view.itemSelectionChanged.connect(self._on_card_selection_changed)
        frame_layout.addWidget(self.card_view)
        return frame

    def _build_detail_splitter(self) -> QtWidgets.QSplitter:
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        splitter.setObjectName('WorkbenchDetailSplitter')
        splitter.addWidget(self._build_detail_panel())
        splitter.addWidget(self._build_result_tabs())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _build_detail_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame(self)
        panel.setObjectName('StrategyDetailPanel')
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.description_label = QtWidgets.QLabel('选择策略以查看描述', panel)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName('StrategyDescription')
        layout.addWidget(self.description_label)

        self.param_group = QtWidgets.QGroupBox('策略参数', panel)
        self.param_form = QtWidgets.QFormLayout()
        self.param_form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.param_group.setLayout(self.param_form)
        layout.addWidget(self.param_group)

        preview_box = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton('即时预览', panel)
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
        self.result_tabs.addTab(self._build_scan_tab(), '批量扫描')
        self.result_tabs.addTab(self._build_backtest_tab(), '历史回测')
        return self.result_tabs

    def _build_scan_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget(self)
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

        self.scan_start = QtWidgets.QDateEdit(tab)
        self.scan_start.setCalendarPopup(True)
        self.scan_start.setDate(QtCore.QDate.currentDate().addYears(-1))
        form.addRow('开始日期:', self.scan_start)

        self.scan_end = QtWidgets.QDateEdit(tab)
        self.scan_end.setCalendarPopup(True)
        self.scan_end.setDate(QtCore.QDate.currentDate())
        form.addRow('结束日期:', self.scan_end)
        layout.addLayout(form)

        action_row = QtWidgets.QHBoxLayout()
        self.scan_button = QtWidgets.QPushButton('运行扫描', tab)
        self.scan_button.clicked.connect(self._run_scan)
        action_row.addWidget(self.scan_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.scan_table = QtWidgets.QTableWidget(tab)
        self.scan_table.setColumnCount(4)
        self.scan_table.setHorizontalHeaderLabels(['排名', '股票', '得分', '备注'])
        self.scan_table.horizontalHeader().setStretchLastSection(True)
        self.scan_table.verticalHeader().setVisible(False)
        self.scan_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.scan_table.doubleClicked.connect(self._on_scan_row_activated)
        layout.addWidget(self.scan_table, 1)

        self.scan_log = QtWidgets.QTextEdit(tab)
        self.scan_log.setReadOnly(True)
        self.scan_log.setMaximumHeight(120)
        layout.addWidget(self.scan_log)
        return tab

    def _build_backtest_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        strip, labels = self._create_kpi_strip(['净利润', '最大回撤', '胜率'])
        self.backtest_kpis = labels
        layout.addWidget(strip)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.backtest_universe = QtWidgets.QLineEdit(tab)
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
        layout.addLayout(form)

        action_row = QtWidgets.QHBoxLayout()
        self.backtest_button = QtWidgets.QPushButton('运行回测', tab)
        self.backtest_button.clicked.connect(self._run_backtest)
        action_row.addWidget(self.backtest_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.backtest_log = QtWidgets.QTextEdit(tab)
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

        for definition in definitions:
            if filter_text != '全部' and filter_text not in definition.tags:
                continue
            item = QtWidgets.QListWidgetItem(definition.title)
            item.setData(QtCore.Qt.UserRole, definition.key)
            item.setToolTip(definition.description or '')
            item.setIcon(self._build_strategy_icon(definition))
            self.card_view.addItem(item)

        self.card_view.blockSignals(False)
        if self.card_view.count():
            self.card_view.setCurrentRow(0)
        else:
            self._set_current_strategy(None)

    def _build_strategy_icon(self, definition: StrategyDefinition) -> QtGui.QIcon:
        colors = ['#4DD0E1', '#82B1FF', '#FFAB91', '#B388FF', '#80CBC4']
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
    def _resolve_universe(self, text_field: QtWidgets.QLineEdit) -> List[str]:
        raw = text_field.text().strip()
        if raw:
            return [token.strip() for token in raw.split(',') if token.strip()]
        return self.universe_provider()

    def _run_preview(self) -> None:
        definition = self._current_definition()
        if not definition:
            QtWidgets.QMessageBox.warning(self, '策略缺失', '请选择策略')
            return
        params = self._collect_params()
        try:
            result = self.preview_handler(definition.key, params)
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.critical(self, '策略运行失败', str(exc))
            return
        if result:
            self.preview_status.setText(result.status_message or '已生成标记')
            self.chart_focus_handler()
        else:
            self.preview_status.setText('未生成标记')

    def _run_scan(self) -> None:
        definition = self._current_definition()
        if not definition:
            QtWidgets.QMessageBox.warning(self, '策略缺失', '请选择策略')
            return
        universe = self._resolve_universe(self.scan_universe)
        if not universe:
            QtWidgets.QMessageBox.warning(self, '股票池为空', '请先加载股票列表')
            return
        db_path = self.db_path_provider()
        if not db_path or not Path(db_path).exists():
            QtWidgets.QMessageBox.warning(self, '缺少数据库', '请先选择数据库文件')
            return

        request = ScanRequest(
            strategy_key=definition.key,
            universe=universe,
            start_date=self.scan_start.date().toPyDate(),
            end_date=self.scan_end.date().toPyDate(),
            params=self._collect_params(),
        )
        self.scan_log.append('开始扫描...')
        try:
            results = self.scanner.run(request, db_path)
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.critical(self, '扫描失败', str(exc))
            return
        self._populate_scan_results(results)

    def _populate_scan_results(self, results: List[ScanResult]) -> None:
        self.scan_results = results
        self.scan_table.setRowCount(len(results))
        for row, result in enumerate(results):
            self.scan_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(row + 1)))
            self.scan_table.setItem(row, 1, QtWidgets.QTableWidgetItem(result.symbol))
            self.scan_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(result.score)))
            self.scan_table.setItem(row, 3, QtWidgets.QTableWidgetItem(result.metadata.get('status', '')))
        self.scan_log.append(f'扫描完成，共 {len(results)} 条结果')
        self._update_scan_kpis(results)

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

    def _append_scan_log(self, message: str) -> None:
        self.scan_log.append(message)

    def _run_backtest(self) -> None:
        definition = self._current_definition()
        if not definition:
            QtWidgets.QMessageBox.warning(self, '策略缺失', '请选择策略')
            return
        universe = self._resolve_universe(self.backtest_universe)
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
        )
        self.backtest_log.append('开始回测...')
        self.engine.run(request, db_path)

    def _append_backtest_log(self, message: str) -> None:
        self.backtest_log.append(message)

    def _on_backtest_finished(self, result: BacktestResult) -> None:
        self.backtest_log.append('回测完成')
        self.backtest_log.append(str(result.metrics))
        self.backtest_log.append('---')
        self._update_backtest_kpis(result)

    def _update_backtest_kpis(self, result: BacktestResult) -> None:
        net = result.metrics.get('net_profit', 0.0)
        drawdown = result.metrics.get('max_drawdown', 0.0)
        trades = result.trades
        wins = sum(1 for trade in trades if trade.get('pnl', 0) > 0)
        win_rate = wins / len(trades) if trades else 0.0
        self._assign_kpi_values(self.backtest_kpis, {
            '净利润': f'{net:.2f}',
            '最大回撤': f'{drawdown:.2f}',
            '胜率': f'{win_rate * 100:.1f}%',
        })

    def _assign_kpi_values(self, kpis: Dict[str, QtWidgets.QLabel], values: Dict[str, str]) -> None:
        for key, widget in kpis.items():
            widget.setText(values.get(key, '--'))

    def _on_backtest_failed(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, '回测失败', message)
