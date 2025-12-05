# displays/base.py

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Protocol
from dataclasses import dataclass


@dataclass
class DisplayResult:
    """策略显示结果的标准数据结构"""
    strategy_name: str
    markers: List[Dict[str, Any]] = None
    overlays: List[Dict[str, Any]] = None
    annotations: List[Dict[str, Any]] = None
    status_message: Optional[str] = None
    extra_data: Dict[str, Any] = None

    def __post_init__(self):
        if self.markers is None:
            self.markers = []
        if self.overlays is None:
            self.overlays = []
        if self.annotations is None:
            self.annotations = []
        if self.extra_data is None:
            self.extra_data = {}


class DisplayInterface(Protocol):
    """显示接口协议"""

    def display_result(self, result: DisplayResult) -> None:
        """显示策略结果"""
        ...

    def clear_strategy_display(self, strategy_name: str) -> None:
        """清除指定策略的显示"""
        ...

    def clear_all_displays(self) -> None:
        """清除所有策略的显示"""
        ...


class DisplayManager:
    """显示管理器"""

    def __init__(self):
        self._displays: Dict[str, DisplayInterface] = {}
        self._active_results: Dict[str, DisplayResult] = {}

    def register_display(self, name: str, display: DisplayInterface) -> None:
        """注册显示器"""
        self._displays[name] = display

    def get_display(self, name: str) -> Optional[DisplayInterface]:
        """获取显示器"""
        return self._displays.get(name)

    def display_result(self, result: DisplayResult) -> None:
        """显示策略结果"""
        # 存储结果
        self._active_results[result.strategy_name] = result

        # 显示到所有注册的显示器
        for display in self._displays.values():
            display.display_result(result)

    def clear_strategy_display(self, strategy_name: str) -> None:
        """清除指定策略的显示"""
        if strategy_name in self._active_results:
            del self._active_results[strategy_name]

        for display in self._displays.values():
            display.clear_strategy_display(strategy_name)

    def clear_all_displays(self) -> None:
        """清除所有显示"""
        self._active_results.clear()

        for display in self._displays.values():
            display.clear_all_displays()

    def get_current_markers(self) -> List[Dict[str, Any]]:
        """获取当前所有活跃的markers"""
        all_markers = []
        for result in self._active_results.values():
            all_markers.extend(result.markers)
        return all_markers

    def get_current_overlays(self) -> List[Dict[str, Any]]:
        """获取当前所有活跃的overlays"""
        all_overlays = []
        for result in self._active_results.values():
            all_overlays.extend(result.overlays)
        return all_overlays