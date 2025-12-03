from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]

from .kline_controller import KLineController

try:
    from ..strategies.zigzag_wave_peaks_valleys import ZigZagWavePeaksValleysStrategy  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    ZigZagWavePeaksValleysStrategy = None


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

        markers = result.get("markers", []) if isinstance(result, dict) else result.markers
        overlays: List[Dict[str, Any]] = []
        controller.set_markers(markers, overlays)
        controller.render_from_database(current_table, markers=markers, overlays=overlays)

        status_message = result.get("status_message", "") if isinstance(result, dict) else result.status_message
        self.status_bar.showMessage(status_message or "ZigZag 检测完成")
        self._log("ZigZag 策略执行完成")


__all__ = ["StrategyMenuController"]
