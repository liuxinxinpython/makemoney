from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]

from .kline_controller import KLineController
from .panels import StrategyWorkbenchPanel

try:
    from ..displays import DisplayResult  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    DisplayResult = None

try:
    from ..strategies.zigzag_wave_peaks_valleys import ZigZagWavePeaksValleysStrategy  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    ZigZagWavePeaksValleysStrategy = None

try:
    from ..strategies.chan_theory_strategy import ChanTheoryStrategy  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    ChanTheoryStrategy = None

try:
    from ..strategies.global_trading_strategies import (  # type: ignore[import-not-found]
        DonchianBreakoutStrategy,
        MovingAverageCrossoverStrategy,
        RSIMeanReversionStrategy,
    )
except Exception:  # pragma: no cover - optional import
    DonchianBreakoutStrategy = None
    MovingAverageCrossoverStrategy = None
    RSIMeanReversionStrategy = None

try:
    from ..rendering import (  # type: ignore[import-not-found]
        ECHARTS_PREVIEW_TEMPLATE_PATH,
        render_echarts_preview,
    )
except Exception:  # pragma: no cover - optional import
    render_echarts_preview = None
    ECHARTS_PREVIEW_TEMPLATE_PATH = None

try:
    from .echarts_preview_dialog import EChartsPreviewDialog
except Exception:  # pragma: no cover - optional import
    EChartsPreviewDialog = None

try:
    from ..research import (  # type: ignore[import-not-found]
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
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.parent_window = parent_window
        self.status_bar = status_bar
        self.kline_controller = kline_controller
        self._db_path_getter = db_path_getter
        self._log = log_handler

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
        result = self.strategy_registry.run_strategy(strategy_key, context)
        if result:
            self.kline_controller.set_markers(list(result.markers), list(result.overlays))
            self.kline_controller.render_from_database(table, list(result.markers), list(result.overlays))
            if result.status_message:
                self.status_bar.showMessage(result.status_message)
            self._show_echarts_preview(strategy_key, result)
        return result

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
        base_markers = list(result.markers)
        preview_markers = self._augment_markers_with_trade_signals(
            base_markers,
            result.extra_data,
            strategy_key=strategy_key,
        )
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

        if not self.strategy_registry.get("zigzag_wave_peaks_valleys"):
            definitions.append(
                StrategyDefinition(
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
            )

        if ChanTheoryStrategy is not None and not self.strategy_registry.get("chan_theory"):
            definitions.append(
                StrategyDefinition(
                    key="chan_theory",
                    title="缠论买卖点",
                    description="基于缠论分型/笔/中枢识别一买、二买、一卖、二卖信号",
                    handler=self._chan_strategy_handler,
                    category="形态识别",
                    parameters=[
                        StrategyParameter(
                            key="swing_window",
                            label="分型窗口",
                            type="number",
                            default=3,
                            description="检测分型时向前向后比较的K线数量",
                        ),
                        StrategyParameter(
                            key="min_move_pct",
                            label="最小笔幅度(%)",
                            type="number",
                            default=3.0,
                            description="小于该幅度的波动不构成有效笔",
                        ),
                        StrategyParameter(
                            key="divergence_pct",
                            label="背驰阈值(%)",
                            type="number",
                            default=5.0,
                            description="一二买卖判断时要求的高低点抬升/下降幅度",
                        ),
                    ],
                    tags=["形态识别", "趋势跟踪"],
                )
            )

        if MovingAverageCrossoverStrategy is not None and not self.strategy_registry.get("ma_crossover"):
            definitions.append(
                StrategyDefinition(
                    key="ma_crossover",
                    title="MA 金叉/死叉",
                    description="经典均线金叉死叉策略, 在全球市场广泛使用的趋势跟踪方法。",
                    handler=self._ma_crossover_strategy_handler,
                    category="趋势跟踪",
                    parameters=[
                        StrategyParameter(
                            key="short_window",
                            label="短周期",
                            type="number",
                            default=20,
                            description="较快均线窗口, 常用 5/10/20。",
                        ),
                        StrategyParameter(
                            key="long_window",
                            label="长周期",
                            type="number",
                            default=50,
                            description="较慢均线窗口, 常用 30/50/60。",
                        ),
                    ],
                    tags=["趋势", "全球策略"],
                )
            )

        if RSIMeanReversionStrategy is not None and not self.strategy_registry.get("rsi_reversion"):
            definitions.append(
                StrategyDefinition(
                    key="rsi_reversion",
                    title="RSI 超买超卖",
                    description="RSI 反转策略, 在强势/弱势区间提供买卖提示。",
                    handler=self._rsi_strategy_handler,
                    category="动量/反转",
                    parameters=[
                        StrategyParameter(
                            key="period",
                            label="RSI 周期",
                            type="number",
                            default=14,
                            description="计算 RSI 的回看窗口, 默认为 14。",
                        ),
                        StrategyParameter(
                            key="oversold",
                            label="超卖阈值",
                            type="number",
                            default=30,
                            description="RSI 低于该值触发买入。",
                        ),
                        StrategyParameter(
                            key="overbought",
                            label="超买阈值",
                            type="number",
                            default=70,
                            description="RSI 高于该值触发卖出。",
                        ),
                    ],
                    tags=["动量", "全球策略"],
                )
            )

        if DonchianBreakoutStrategy is not None and not self.strategy_registry.get("donchian_breakout"):
            definitions.append(
                StrategyDefinition(
                    key="donchian_breakout",
                    title="唐奇安通道",
                    description="唐奇安价格通道突破策略, CTA 与海龟交易的核心逻辑。",
                    handler=self._donchian_strategy_handler,
                    category="趋势跟踪",
                    parameters=[
                        StrategyParameter(
                            key="lookback",
                            label="回看周期",
                            type="number",
                            default=20,
                            description="构建唐奇安通道的历史窗口长度。",
                        ),
                    ],
                    tags=["趋势", "全球策略"],
                )
            )

        for definition in definitions:
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
        return self._serialize_run_result("zigzag_wave_peaks_valleys", raw_result)

    def _chan_strategy_handler(self, context: "StrategyContext") -> "StrategyRunResult":
        if ChanTheoryStrategy is None or StrategyRunResult is None:
            raise RuntimeError("缠论策略不可用")
        try:
            swing_window = int(float(context.params.get("swing_window", 3)))
        except (TypeError, ValueError):
            swing_window = 3
        try:
            min_move_pct = float(context.params.get("min_move_pct", 3.0))
        except (TypeError, ValueError):
            min_move_pct = 3.0
        try:
            divergence_pct = float(context.params.get("divergence_pct", 5.0))
        except (TypeError, ValueError):
            divergence_pct = 5.0

        strategy = ChanTheoryStrategy(
            swing_window=max(2, swing_window),
            min_move_pct=max(0.0005, min_move_pct / 100.0),
            divergence_pct=max(0.0005, divergence_pct / 100.0),
        )
        raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
        return self._serialize_run_result("chan_theory", raw_result)

    def _ma_crossover_strategy_handler(self, context: "StrategyContext") -> "StrategyRunResult":
        if MovingAverageCrossoverStrategy is None:
            raise RuntimeError("均线策略不可用")
        try:
            short_window = int(float(context.params.get("short_window", 20)))
        except (TypeError, ValueError):
            short_window = 20
        try:
            long_window = int(float(context.params.get("long_window", 50)))
        except (TypeError, ValueError):
            long_window = 50
        short_window = max(3, short_window)
        long_window = max(short_window + 1, long_window)

        strategy = MovingAverageCrossoverStrategy(short_window=short_window, long_window=long_window)
        raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
        return self._serialize_run_result("ma_crossover", raw_result)

    def _rsi_strategy_handler(self, context: "StrategyContext") -> "StrategyRunResult":
        if RSIMeanReversionStrategy is None:
            raise RuntimeError("RSI 策略不可用")
        try:
            period = int(float(context.params.get("period", 14)))
        except (TypeError, ValueError):
            period = 14
        try:
            oversold = float(context.params.get("oversold", 30.0))
        except (TypeError, ValueError):
            oversold = 30.0
        try:
            overbought = float(context.params.get("overbought", 70.0))
        except (TypeError, ValueError):
            overbought = 70.0

        period = max(2, period)
        oversold = max(0.0, min(oversold, 99.0))
        overbought = max(oversold + 1.0, min(overbought, 100.0))

        strategy = RSIMeanReversionStrategy(period=period, oversold=oversold, overbought=overbought)
        raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
        return self._serialize_run_result("rsi_reversion", raw_result)

    def _donchian_strategy_handler(self, context: "StrategyContext") -> "StrategyRunResult":
        if DonchianBreakoutStrategy is None:
            raise RuntimeError("唐奇安策略不可用")
        try:
            lookback = int(float(context.params.get("lookback", 20)))
        except (TypeError, ValueError):
            lookback = 20
        lookback = max(5, lookback)

        strategy = DonchianBreakoutStrategy(lookback=lookback)
        raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
        return self._serialize_run_result("donchian_breakout", raw_result)

    def _serialize_run_result(self, strategy_name: str, raw_result: Any) -> "StrategyRunResult":
        if StrategyRunResult is None:
            raise RuntimeError("StrategyRunResult 类型不可用")
        markers: List[Dict[str, Any]] = []
        overlays: List[Dict[str, Any]] = []
        status_message: Optional[str] = None
        extra_data: Dict[str, Any] = {}

        if raw_result is None:
            pass
        elif DisplayResult is not None and isinstance(raw_result, DisplayResult):
            markers = list(getattr(raw_result, "markers", []) or [])
            overlays = list(getattr(raw_result, "overlays", []) or [])
            status_message = getattr(raw_result, "status_message", None)
            extra_data = dict(getattr(raw_result, "extra_data", {}) or {})
        else:
            markers = list(raw_result.get("markers", []) or [])  # type: ignore[union-attr]
            overlays = list(raw_result.get("overlays", []) or [])  # type: ignore[union-attr]
            status_message = raw_result.get("status_message")  # type: ignore[union-attr]
            extra_data = dict(raw_result.get("extra_data", {}) or {})  # type: ignore[union-attr]

        return StrategyRunResult(
            strategy_name=strategy_name,
            markers=markers,
            overlays=overlays,
            status_message=status_message,
            extra_data=extra_data,
        )

    def _augment_markers_with_trade_signals(
        self,
        markers: List[Dict[str, Any]],
        extra_data: Optional[Dict[str, Any]],
        *,
        strategy_key: str,
    ) -> List[Dict[str, Any]]:
        trades = list((extra_data or {}).get("trades", []) or [])
        if not trades:
            return markers
        enriched = list(markers)
        buy_times = {m.get("time") for m in markers if isinstance(m.get("text"), str) and "BUY" in m["text"].upper()}
        sell_times = {m.get("time") for m in markers if isinstance(m.get("text"), str) and "SELL" in m["text"].upper()}

        for idx, trade in enumerate(trades):
            entry_time = trade.get("entry_time") or trade.get("entryTime")
            entry_price = self._safe_float(trade.get("entry_price") or trade.get("entryPrice"))
            entry_label = trade.get("entry_reason") or trade.get("entryReason")
            if entry_time and entry_time not in buy_times:
                text = entry_label or (f"BUY {entry_price:.2f}" if entry_price is not None else "BUY")
                enriched.append(
                    {
                        "id": f"{strategy_key}_buy_{idx}",
                        "time": entry_time,
                        "position": "belowBar",
                        "color": "#22c55e",
                        "shape": "triangle",
                        "text": text,
                    }
                )
                buy_times.add(entry_time)

            exit_time = trade.get("exit_time") or trade.get("exitTime")
            exit_price = self._safe_float(trade.get("exit_price") or trade.get("exitPrice"))
            exit_label = trade.get("exit_reason") or trade.get("exitReason")
            if exit_time and exit_time not in sell_times:
                text = exit_label or (f"SELL {exit_price:.2f}" if exit_price is not None else "SELL")
                enriched.append(
                    {
                        "id": f"{strategy_key}_sell_{idx}",
                        "time": exit_time,
                        "position": "aboveBar",
                        "color": "#f87171",
                        "shape": "triangle",
                        "text": text,
                    }
                )
                sell_times.add(exit_time)
        return enriched

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


__all__ = ["StrategyWorkbenchController"]
