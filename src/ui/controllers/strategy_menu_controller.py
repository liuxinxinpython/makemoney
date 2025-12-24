from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]

from .kline_controller import KLineController

try:
    from ...strategies.zigzag_wave_peaks_valleys import ZigZagWavePeaksValleysStrategy  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    ZigZagWavePeaksValleysStrategy = None

try:
    from ...strategies.zigzag_double_retest import ZigZagDoubleRetestStrategy  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    ZigZagDoubleRetestStrategy = None

try:
    from ...rendering import ECHARTS_PREVIEW_TEMPLATE_PATH, render_echarts_preview  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    render_echarts_preview = None
    ECHARTS_PREVIEW_TEMPLATE_PATH = None

try:
    from ..echarts_preview_dialog import EChartsPreviewDialog
except Exception:  # pragma: no cover - optional import
    EChartsPreviewDialog = None


class StrategyMenuController(QtCore.QObject):
    """负责选股菜单的策略注册与触发逻辑。"""

    def __init__(
        self,
        *,
        parent_window: QtWidgets.QMainWindow,
        menu: QtWidgets.QMenu,
        status_bar: QtWidgets.QStatusBar,
        kline_controller: Optional[KLineController],
        db_path_getter: Callable[[], Path],
        log_handler: Callable[[str], None],
        selector_available: bool,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.parent_window = parent_window
        self.menu = menu
        self.status_bar = status_bar
        self.kline_controller = kline_controller
        self._db_path_getter = db_path_getter
        self._log = log_handler
        self._selector_available = selector_available
        self._strategy_definitions: List[Dict[str, Any]] = []
        self._actions: List[QtWidgets.QAction] = []
        self._echarts_dialog: Optional[EChartsPreviewDialog] = None

    def clear(self) -> None:
        self._strategy_definitions.clear()
        self._actions.clear()
        self.menu.clear()

    def register_builtin_strategies(self) -> None:
        self.clear()
        self._register_strategy(
            key="zigzag_wave_peaks_valleys",
            title="ZigZag波峰波谷",
            handler=self._handle_zigzag_wave_peaks_valleys,
            requires_selector=False,
            description="使用 ZigZag 算法在图表中识别价格数据的波峰与波谷形态",
        )
        self._register_strategy(
            key="zigzag_double_retest",
            title="ZigZag双回踩版",
            handler=self._handle_zigzag_double_retest,
            requires_selector=False,
            description="大波段回踩后再出现小波段回踩并反弹触发买点的扩展版",
        )
        self._rebuild_menu()

    # ------------------------------------------------------------------
    # 策略注册与菜单构建
    # ------------------------------------------------------------------
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
        self._strategy_definitions.append(definition)

    def _strategy_enabled(self, definition: Dict[str, Any]) -> bool:
        if definition.get("requires_selector") and not self._selector_available:
            return False
        return True

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        self._actions.clear()

        for definition in self._strategy_definitions:
            action = QtWidgets.QAction(definition["title"], self.parent_window)
            action.triggered.connect(definition["handler"])
            action.setEnabled(self._strategy_enabled(definition))
            description = definition.get("description")
            if description:
                action.setStatusTip(description)
                action.setToolTip(description)
            self.menu.addAction(action)
            self._actions.append(action)

        if not self._actions:
            placeholder = QtWidgets.QAction("暂无可用策略", self.parent_window)
            placeholder.setEnabled(False)
            self.menu.addAction(placeholder)

    # ------------------------------------------------------------------
    # 策略实现
    # ------------------------------------------------------------------
    def _handle_zigzag_wave_peaks_valleys(self) -> None:
        controller = self.kline_controller
        if controller is None or ZigZagWavePeaksValleysStrategy is None:
            QtWidgets.QMessageBox.critical(self.parent_window, "策略不可用", "ZigZag 模块未正确初始化。")
            return

        current_table = controller.current_table
        if not current_table:
            QtWidgets.QMessageBox.warning(self.parent_window, "未选择标的", "请先选择一个标的再执行 ZigZag 检测。")
            return

        db_path = self._db_path_getter()
        if not db_path.exists():
            QtWidgets.QMessageBox.warning(self.parent_window, "缺少数据库", "请先选择有效的 SQLite 数据库文件。")
            return

        try:
            strategy = ZigZagWavePeaksValleysStrategy()
            result = strategy.scan_current_symbol(db_path, current_table)
        except Exception as exc:  # pragma: no cover - interactive feedback
            QtWidgets.QMessageBox.critical(self.parent_window, "ZigZag 检测失败", str(exc))
            self._log(f"ZigZag 检测失败: {exc}")
            return

        if not result:
            QtWidgets.QMessageBox.information(
                self.parent_window,
                "未检出波峰波谷",
                "当前标的未检测到明显的 ZigZag 波峰波谷。",
            )
            controller.set_markers([], [])
            controller.render_from_database(current_table)
            self.status_bar.showMessage("ZigZag 检测完成 (无标记)")
            return
        extra_data: Dict[str, Any] = {}
        if isinstance(result, dict):
            markers = list(result.get("markers", []) or [])
            overlays = list(result.get("overlays", []) or [])
            status_message = result.get("status_message", "")
            extra_data = dict(result.get("extra_data", {}) or {})
        else:
            markers = list(getattr(result, "markers", []) or [])
            overlays = list(getattr(result, "overlays", []) or [])
            status_message = getattr(result, "status_message", "")
            extra_data = dict(getattr(result, "extra_data", {}) or {})

        controller.set_markers(markers, overlays)
        controller.render_from_database(current_table)
        self._show_echarts_preview("ZigZag波峰波谷", markers, overlays, extra_data)

        self.status_bar.showMessage(status_message or "ZigZag 检测完成")
        self._log("ZigZag 策略执行完成")

    def _handle_zigzag_double_retest(self) -> None:
        controller = self.kline_controller
        if controller is None or ZigZagDoubleRetestStrategy is None:
            QtWidgets.QMessageBox.critical(self.parent_window, "策略不可用", "ZigZag 模块未正确初始化。")
            return

        current_table = controller.current_table
        if not current_table:
            QtWidgets.QMessageBox.warning(self.parent_window, "未选择标的", "请先选择一个标的再执行 ZigZag 检测。")
            return

        db_path = self._db_path_getter()
        if not db_path.exists():
            QtWidgets.QMessageBox.warning(self.parent_window, "缺少数据库", "请先选择有效的 SQLite 数据库文件。")
            return

        try:
            strategy = ZigZagDoubleRetestStrategy()
            result = strategy.scan_current_symbol(db_path, current_table)
        except Exception as exc:  # pragma: no cover - interactive feedback
            QtWidgets.QMessageBox.critical(self.parent_window, "ZigZag 双回踩检测失败", str(exc))
            self._log(f"ZigZag 双回踩检测失败: {exc}")
            return

        if not result:
            QtWidgets.QMessageBox.information(
                self.parent_window,
                "未检出双回踩形态",
                "当前标的未检测到符合“大波段回踩+小波段回踩”条件的形态。",
            )
            controller.set_markers([], [])
            controller.render_from_database(current_table)
            self.status_bar.showMessage("ZigZag 双回踩检测完成 (无标记)")
            return
        extra_data: Dict[str, Any] = {}
        if isinstance(result, dict):
            markers = list(result.get("markers", []) or [])
            overlays = list(result.get("overlays", []) or [])
            status_message = result.get("status_message", "")
            extra_data = dict(result.get("extra_data", {}) or {})
        else:
            markers = list(getattr(result, "markers", []) or [])
            overlays = list(getattr(result, "overlays", []) or [])
            status_message = getattr(result, "status_message", "")
            extra_data = dict(getattr(result, "extra_data", {}) or {})

        controller.set_markers(markers, overlays)
        controller.render_from_database(current_table)
        self._show_echarts_preview("ZigZag双回踩版", markers, overlays, extra_data)

        self.status_bar.showMessage(status_message or "ZigZag 双回踩检测完成")
        self._log("ZigZag 双回踩策略执行完成")

    def _ensure_echarts_dialog(self) -> Optional[EChartsPreviewDialog]:
        if EChartsPreviewDialog is None or render_echarts_preview is None:
            return None
        if self._echarts_dialog is None:
            template_path = ECHARTS_PREVIEW_TEMPLATE_PATH
            if template_path is None:
                return None
            self._echarts_dialog = EChartsPreviewDialog(template_path, self.parent_window)
        return self._echarts_dialog

    def _show_echarts_preview(
        self,
        title: str,
        markers: List[Dict[str, Any]],
        overlays: List[Dict[str, Any]],
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.kline_controller is None:
            return
        dialog = self._ensure_echarts_dialog()
        if dialog is None:
            return
        candles = getattr(self.kline_controller, "current_candles", None)
        if not candles:
            return
        volumes = getattr(self.kline_controller, "current_volumes", None)
        instrument = getattr(self.kline_controller, "current_instrument", None)
        strokes = list((extra_data or {}).get("strokes", []) or [])
        preview_markers = self._markers_with_trade_signals(markers, extra_data, prefix=title)
        try:
            html = render_echarts_preview(
                candles=candles,
                volumes=list(volumes or []),
                markers=preview_markers,
                overlays=overlays,
                instrument=instrument,
                strokes=strokes,
                title=title,
            )
        except Exception as exc:
            self._log(f"ECharts 预览渲染失败: {exc}")
            return
        dialog.show_html(f"{title} · ECharts", html)

    @staticmethod
    def _markers_with_trade_signals(
        markers: List[Dict[str, Any]],
        extra_data: Optional[Dict[str, Any]],
        *,
        prefix: str,
    ) -> List[Dict[str, Any]]:
        trades = list((extra_data or {}).get("trades", []) or [])
        if not trades:
            return markers
        enriched = list(markers)
        buy_times = {m.get("time") for m in markers if isinstance(m.get("text"), str) and "BUY" in m["text"].upper()}
        sell_times = {m.get("time") for m in markers if isinstance(m.get("text"), str) and "SELL" in m["text"].upper()}
        for idx, trade in enumerate(trades):
            entry_time = trade.get("entry_time") or trade.get("entryTime")
            entry_price = StrategyMenuController._safe_float(trade.get("entry_price") or trade.get("entryPrice"))
            entry_label = trade.get("entry_reason") or trade.get("entryReason")
            if entry_time and entry_time not in buy_times:
                text = entry_label or (f"BUY {entry_price:.2f}" if entry_price is not None else "BUY")
                enriched.append(
                    {
                        "id": f"{prefix}_buy_{idx}",
                        "time": entry_time,
                        "position": "belowBar",
                        "color": "#22c55e",
                        "shape": "triangle",
                        "text": text,
                    }
                )
                buy_times.add(entry_time)

            exit_time = trade.get("exit_time") or trade.get("exitTime")
            exit_price = StrategyMenuController._safe_float(trade.get("exit_price") or trade.get("exitPrice"))
            exit_label = trade.get("exit_reason") or trade.get("exitReason")
            if exit_time and exit_time not in sell_times:
                text = exit_label or (f"SELL {exit_price:.2f}" if exit_price is not None else "SELL")
                enriched.append(
                    {
                        "id": f"{prefix}_sell_{idx}",
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


__all__ = ["StrategyMenuController"]
