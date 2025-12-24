from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]

from .kline_controller import KLineController
from ..panels import StrategyWorkbenchPanel
from ...strategies.helpers import augment_markers_with_trade_signals

try:
    from ...strategies.zigzag_wave_peaks_valleys import (
        ZIGZAG_STRATEGY_PARAMETERS,
        run_zigzag_workbench,
    )
    from ...strategies.zigzag_double_retest import (
        ZIGZAG_DOUBLE_RETEST_PARAMETERS,
        run_zigzag_double_retest_workbench,
    )
    from ...strategies.zigzag_volume_double_long import (
        ZIGZAG_VOLUME_DOUBLE_LONG_PARAMETERS,
        run_zigzag_volume_double_long_workbench,
    )
except Exception:  # pragma: no cover - optional import
    ZIGZAG_STRATEGY_PARAMETERS = []
    run_zigzag_workbench = None
    ZIGZAG_DOUBLE_RETEST_PARAMETERS = []
    run_zigzag_double_retest_workbench = None
    ZIGZAG_VOLUME_DOUBLE_LONG_PARAMETERS = []
    run_zigzag_volume_double_long_workbench = None

try:
    from ...strategies.chan_theory_strategy import (
        CHAN_STRATEGY_PARAMETERS,
        run_chan_workbench,
    )
except Exception:  # pragma: no cover - optional import
    CHAN_STRATEGY_PARAMETERS = []
    run_chan_workbench = None

try:
    from ...strategies.global_trading_strategies import (
        PARAMETERS_BY_STRATEGY,
        run_ma_workbench,
        run_rsi_workbench,
        run_donchian_workbench,
    )
except Exception:  # pragma: no cover - optional import
    PARAMETERS_BY_STRATEGY = {
        "ma": [],
        "rsi": [],
        "donchian": [],
    }
    run_ma_workbench = None
    run_rsi_workbench = None
    run_donchian_workbench = None

try:
    from ...rendering import (  # type: ignore[import-not-found]
        ECHARTS_PREVIEW_TEMPLATE_PATH,
        render_echarts_preview,
    )
except Exception:  # pragma: no cover - optional import
    render_echarts_preview = None
    ECHARTS_PREVIEW_TEMPLATE_PATH = None

try:
    from ..echarts_preview_dialog import EChartsPreviewDialog
except Exception:  # pragma: no cover - optional import
    EChartsPreviewDialog = None

try:
    from ...research import (  # type: ignore[import-not-found]
        StrategyContext,
        StrategyDefinition,
        StrategyParameter,
        StrategyRegistry,
        StrategyRunResult,
        global_strategy_registry,
    )
except Exception:  # pragma: no cover - optional import
    StrategyContext = None
    StrategyDefinition = None
    StrategyParameter = None
    StrategyRegistry = None
    StrategyRunResult = None
    global_strategy_registry = None


class StrategyWorkbenchController(QtCore.QObject):
    """封装策略工作台(Dock)的创建、策略注册以及预览回调。"""

    def __init__(
        self,
        *,
        parent_window: QtWidgets.QMainWindow,
        status_bar: QtWidgets.QStatusBar,
        kline_controller: KLineController,
        db_path_getter: Callable[[], Path],
        log_handler: Callable[[str], None],
        watchlist_adder: Optional[Callable[[List[Tuple[str, str]]], None]] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.parent_window = parent_window
        self.status_bar = status_bar
        self.kline_controller = kline_controller
        self._db_path_getter = db_path_getter
        self._log = log_handler
        self._add_to_watchlist = watchlist_adder

        self.strategy_registry: Optional[StrategyRegistry] = None
        self.workbench_panel: Optional[StrategyWorkbenchPanel] = None
        self.workbench_dock: Optional[QtWidgets.QDockWidget] = None
        self.toggle_action: Optional[QtWidgets.QAction] = None
        self._echarts_dialog: Optional[EChartsPreviewDialog] = None
        self._symbol_listener_attached = False

    def bind_toggle_action(self, action: QtWidgets.QAction) -> None:
        self.toggle_action = action
        self.toggle_action.triggered.connect(self.toggle_visibility)
        self.toggle_action.setEnabled(False)

    def initialize(self) -> None:
        if self.workbench_dock is not None:
            return
        if not self._ensure_registry():
            return
        dock = QtWidgets.QDockWidget("策略工作台", self.parent_window)
        dock.setObjectName("strategy_workbench_dock")
        panel = self._create_panel(dock)
        if panel is None:
            dock.deleteLater()
            return
        dock.setWidget(panel)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        dock.setMinimumWidth(560)
        dock.setMaximumWidth(max(960, int(self.parent_window.width() * 0.7)))
        dock.setFeatures(dock.features() | QtWidgets.QDockWidget.DockWidgetFloatable)
        self.parent_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        try:
            target_width = max(700, int(self.parent_window.width() * 0.5))
            self.parent_window.resizeDocks([dock], [target_width], QtCore.Qt.Horizontal)
        except Exception:
            dock.resize(max(720, dock.width()), dock.height())
        dock.visibilityChanged.connect(self._on_visibility_changed)

        self.workbench_dock = dock

        if self.toggle_action:
            self.toggle_action.setEnabled(True)
            self.toggle_action.blockSignals(True)
            self.toggle_action.setChecked(True)
            self.toggle_action.blockSignals(False)

        self._attach_symbol_listener()
        self._update_panel_selection()

    def toggle_visibility(self, checked: bool) -> None:
        if checked and self.workbench_dock is None:
            self.initialize()
        if self.workbench_dock:
            self.workbench_dock.setVisible(checked)
            if checked:
                self.workbench_dock.raise_()
        elif self.toggle_action:
            self.toggle_action.blockSignals(True)
            self.toggle_action.setChecked(False)
            self.toggle_action.blockSignals(False)

    def create_embedded_panel(self, parent: QtWidgets.QWidget) -> Optional[StrategyWorkbenchPanel]:
        if not self._ensure_registry():
            return None
        panel = self._create_panel(parent)
        if panel is None:
            return None
        self._attach_symbol_listener()
        self._update_panel_selection()
        return panel

    def _ensure_registry(self) -> bool:
        if self.strategy_registry is not None:
            return True
        if StrategyWorkbenchPanel is None or global_strategy_registry is None:
            return False
        try:
            self.strategy_registry = global_strategy_registry()
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(f"初始化策略注册中心失败: {exc}")
            self.strategy_registry = None
            return False
        self._register_builtin_strategies()
        return self.strategy_registry is not None

    def _create_panel(self, parent: QtWidgets.QWidget) -> Optional[StrategyWorkbenchPanel]:
        if not self.strategy_registry:
            return None
        if self.workbench_panel is None:
            self.workbench_panel = StrategyWorkbenchPanel(
                registry=self.strategy_registry,
                universe_provider=self.kline_controller.current_universe,
                selected_symbol_provider=lambda: self.kline_controller.current_table,
                db_path_provider=self._db_path_getter,
                preview_handler=self._run_workbench_preview,
                chart_focus_handler=self.kline_controller.focus_chart,
                load_symbol_handler=self.kline_controller.select_symbol,
                render_markers_handler=self._render_custom_markers,
                add_to_watchlist=self._add_to_watchlist,
                parent=parent,
            )
        else:
            self.workbench_panel.setParent(parent)
        return self.workbench_panel

    def _attach_symbol_listener(self) -> None:
        if self._symbol_listener_attached or not self.kline_controller:
            return
        self.kline_controller.symbol_changed.connect(self._on_symbol_changed)
        self._symbol_listener_attached = True

    def _update_panel_selection(self) -> None:
        if not (self.workbench_panel and self.kline_controller):
            return
        current = self.kline_controller.current_symbol or self.kline_controller.current_table
        if current:
            self.workbench_panel.update_selected_symbol(current)

    def _on_visibility_changed(self, visible: bool) -> None:
        if self.toggle_action:
            self.toggle_action.blockSignals(True)
            self.toggle_action.setChecked(visible)
            self.toggle_action.blockSignals(False)

    def _on_symbol_changed(self, table_name: str) -> None:
        if not self.workbench_panel:
            return
        symbol = self.kline_controller.current_symbol or table_name
        self.workbench_panel.update_selected_symbol(symbol)

    def _run_workbench_preview(self, strategy_key: str, params: Dict[str, Any]) -> "Optional[StrategyRunResult]":
        if not self.strategy_registry or StrategyContext is None:
            raise RuntimeError("策略工作台不可用")
        table = self.kline_controller.current_table
        if not table:
            raise RuntimeError("请先选择标的")
        db_path = self._db_path_getter()
        if not db_path.exists():
            raise RuntimeError("数据库文件不存在")

        context = StrategyContext(
            db_path=db_path,
            table_name=table,
            symbol=self.kline_controller.current_symbol or table,
            params=params,
            current_only=True,
            start_date=None,
            end_date=None,
            mode="preview",
        )
        # 先清空旧标记，避免策略切换时残留。
        self.kline_controller.set_markers([], [])
        self.kline_controller.render_from_database(table, [], [])

        result = self.strategy_registry.run_strategy(strategy_key, context)
        if result:
            self.kline_controller.set_markers(list(result.markers), list(result.overlays))
            self.kline_controller.render_from_database(table, list(result.markers), list(result.overlays))
            if result.status_message:
                self.status_bar.showMessage(result.status_message)
            self._show_echarts_preview(strategy_key, result)
        return result

    def _render_custom_markers(
        self,
        table: str,
        markers: List[Dict[str, Any]],
        overlays: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not self.kline_controller or not table:
            return
        self.kline_controller.set_markers(list(markers), list(overlays or []))
        self.kline_controller.render_from_database(table, list(markers), list(overlays or []))

    def _ensure_echarts_dialog(self) -> Optional[EChartsPreviewDialog]:
        if EChartsPreviewDialog is None or render_echarts_preview is None:
            return None
        if self._echarts_dialog is None:
            template_path = ECHARTS_PREVIEW_TEMPLATE_PATH
            if template_path is None:
                return None
            self._echarts_dialog = EChartsPreviewDialog(template_path, self.parent_window)
        return self._echarts_dialog

    def _show_echarts_preview(self, strategy_key: str, result: "StrategyRunResult") -> None:
        dialog = self._ensure_echarts_dialog()
        if dialog is None:
            return
        candles = getattr(self.kline_controller, "current_candles", None)
        if not candles:
            return
        volumes = getattr(self.kline_controller, "current_volumes", None)
        instrument = getattr(self.kline_controller, "current_instrument", None)
        definition_title = None
        if self.strategy_registry:
            definition = self.strategy_registry.get(strategy_key)
            if definition:
                definition_title = definition.title
        title = definition_title or strategy_key
        # 过多标注会让预览卡顿/无法切换，做适度截断
        max_markers = 500
        base_markers = list(result.markers)
        preview_markers = augment_markers_with_trade_signals(
            base_markers,
            result.extra_data,
            strategy_key=strategy_key,
        )
        if len(preview_markers) > max_markers:
            preview_markers = preview_markers[-max_markers:]
        try:
            html = render_echarts_preview(
                candles=candles,
                volumes=list(volumes or []),
                markers=preview_markers,
                overlays=list(result.overlays),
                instrument=instrument,
                strokes=list((result.extra_data or {}).get('strokes', []) or []),
                title=title,
            )
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(f"ECharts 预览渲染失败: {exc}")
            return
        dialog.show_html(f"{title} · ECharts", html)

    def _register_builtin_strategies(self) -> None:
        if not (self.strategy_registry and StrategyDefinition and StrategyParameter):
            return
        definitions: List[StrategyDefinition] = []

        if run_zigzag_workbench is not None and not self.strategy_registry.get("zigzag_wave_peaks_valleys"):
            zigzag_parameters: List[StrategyParameter] = []
            if ZIGZAG_STRATEGY_PARAMETERS:
                zigzag_parameters = list(ZIGZAG_STRATEGY_PARAMETERS)
            elif StrategyParameter is not None:
                zigzag_parameters = [
                    StrategyParameter(
                        key="min_reversal",
                        label="最小反转(%)",
                        type="number",
                        default=5.0,
                        description="忽略幅度低于该百分比的价格波动",
                    )
                ]
            definitions.append(
                StrategyDefinition(
                    key="zigzag_wave_peaks_valleys",
                    title="ZigZag波峰波谷",
                    description="识别 ZigZag 波动形态, 输出波峰/波谷标记与状态信息",
                    handler=run_zigzag_workbench,
                    category="形态识别",
                    parameters=zigzag_parameters,
                    tags=["形态识别", "波动策略"],
                )
            )

        if run_zigzag_double_retest_workbench is not None and not self.strategy_registry.get("zigzag_double_retest"):
            double_params: List[StrategyParameter] = []
            if ZIGZAG_DOUBLE_RETEST_PARAMETERS:
                double_params = list(ZIGZAG_DOUBLE_RETEST_PARAMETERS)
            definitions.append(
                StrategyDefinition(
                    key="zigzag_double_retest",
                    title="ZigZag双回踩再上车",
                    description="大波段回踩后，再出现二次回踩并反弹的买入版本。",
                    handler=run_zigzag_double_retest_workbench,
                    category="形态识别",
                    parameters=double_params,
                    tags=["形态识别", "双回踩"],
                )
            )

        if run_zigzag_volume_double_long_workbench is not None and not self.strategy_registry.get("zigzag_volume_double_long"):
            vol_params: List[StrategyParameter] = []
            if ZIGZAG_VOLUME_DOUBLE_LONG_PARAMETERS:
                vol_params = list(ZIGZAG_VOLUME_DOUBLE_LONG_PARAMETERS)
            definitions.append(
                StrategyDefinition(
                    key="zigzag_volume_double_long",
                    title="ZigZag倍量二次入场",
                    description="主波段回踩后出现首根倍量阳线，再回调后二次倍量阳线买入。",
                    handler=run_zigzag_volume_double_long_workbench,
                    category="形态识别",
                    parameters=vol_params,
                    tags=["形态识别", "成交量"],
                )
            )

        if run_chan_workbench is not None and not self.strategy_registry.get("chan_theory"):
            chan_parameters: List[StrategyParameter] = []
            if CHAN_STRATEGY_PARAMETERS:
                chan_parameters = list(CHAN_STRATEGY_PARAMETERS)
            elif StrategyParameter is not None:
                chan_parameters = [
                    StrategyParameter(
                        key="swing_window",
                        label="分型窗口",
                        type="number",
                        default=3,
                        description="检测分型时向前向后比较的K线数量",
                    )
                ]
            definitions.append(
                StrategyDefinition(
                    key="chan_theory",
                    title="缠论买卖点",
                    description="基于缠论分型/笔/中枢识别一买、二买、一卖、二卖信号",
                    handler=run_chan_workbench,
                    category="形态识别",
                    parameters=chan_parameters,
                    tags=["形态识别", "趋势跟踪"],
                )
            )

        if run_ma_workbench is not None and not self.strategy_registry.get("ma_crossover"):
            ma_params = list(PARAMETERS_BY_STRATEGY.get("ma", []))
            definitions.append(
                StrategyDefinition(
                    key="ma_crossover",
                    title="MA 金叉/死叉",
                    description="经典均线金叉死叉策略, 在全球市场广泛使用的趋势跟踪方法。",
                    handler=run_ma_workbench,
                    category="趋势跟踪",
                    parameters=ma_params,
                    tags=["趋势", "全球策略"],
                )
            )

        if run_rsi_workbench is not None and not self.strategy_registry.get("rsi_reversion"):
            rsi_params = list(PARAMETERS_BY_STRATEGY.get("rsi", []))
            definitions.append(
                StrategyDefinition(
                    key="rsi_reversion",
                    title="RSI 超买超卖",
                    description="RSI 反转策略, 在强势/弱势区间提供买卖提示。",
                    handler=run_rsi_workbench,
                    category="动量/反转",
                    parameters=rsi_params,
                    tags=["动量", "全球策略"],
                )
            )

        if run_donchian_workbench is not None and not self.strategy_registry.get("donchian_breakout"):
            donchian_params = list(PARAMETERS_BY_STRATEGY.get("donchian", []))
            definitions.append(
                StrategyDefinition(
                    key="donchian_breakout",
                    title="唐奇安通道",
                    description="唐奇安价格通道突破策略, CTA 与海龟交易的核心逻辑。",
                    handler=run_donchian_workbench,
                    category="趋势跟踪",
                    parameters=donchian_params,
                    tags=["趋势", "全球策略"],
                )
            )

        for definition in definitions:
            self.strategy_registry.register(definition)

__all__ = ["StrategyWorkbenchController"]
