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

    def bind_toggle_action(self, action: QtWidgets.QAction) -> None:
        self.toggle_action = action
        self.toggle_action.triggered.connect(self.toggle_visibility)
        self.toggle_action.setEnabled(False)

    def initialize(self) -> None:
        if self.workbench_dock is not None:
            return
        if StrategyWorkbenchPanel is None or global_strategy_registry is None:
            return
        try:
            self.strategy_registry = global_strategy_registry()
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(f"初始化策略注册中心失败: {exc}")
            self.strategy_registry = None
            return

        self._register_builtin_strategies()
        if not self.strategy_registry:
            return

        panel = StrategyWorkbenchPanel(
            registry=self.strategy_registry,
            universe_provider=self.kline_controller.current_universe,
            db_path_provider=self._db_path_getter,
            preview_handler=self._run_workbench_preview,
            chart_focus_handler=self.kline_controller.focus_chart,
            load_symbol_handler=self.kline_controller.select_symbol,
            parent=self.parent_window,
        )
        dock = QtWidgets.QDockWidget("策略工作台", self.parent_window)
        dock.setObjectName("strategy_workbench_dock")
        dock.setWidget(panel)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.parent_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        dock.visibilityChanged.connect(self._on_visibility_changed)

        self.workbench_panel = panel
        self.workbench_dock = dock

        if self.toggle_action:
            self.toggle_action.setEnabled(True)
            self.toggle_action.blockSignals(True)
            self.toggle_action.setChecked(True)
            self.toggle_action.blockSignals(False)

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

    def _on_visibility_changed(self, visible: bool) -> None:
        if self.toggle_action:
            self.toggle_action.blockSignals(True)
            self.toggle_action.setChecked(visible)
            self.toggle_action.blockSignals(False)

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
        )
        result = self.strategy_registry.run_strategy(strategy_key, context)
        if result:
            self.kline_controller.set_markers(list(result.markers), list(result.overlays))
            self.kline_controller.render_from_database(table, list(result.markers), list(result.overlays))
            if result.status_message:
                self.status_bar.showMessage(result.status_message)
        return result

    def _register_builtin_strategies(self) -> None:
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


__all__ = ["StrategyWorkbenchController"]
