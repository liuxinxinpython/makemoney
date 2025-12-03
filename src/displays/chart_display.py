# displays/chart_display.py

from typing import List, Dict, Any, Optional
from .base import DisplayInterface, DisplayResult


class ChartDisplay(DisplayInterface):
    """TradingView图表显示器"""

    def __init__(self, chart_renderer):
        """
        Args:
            chart_renderer: 图表渲染器对象，应该有 refresh_chart 方法
        """
        self.chart_renderer = chart_renderer

    def display_result(self, result: DisplayResult) -> None:
        """显示策略结果到图表"""
        # 触发图表刷新
        # 渲染器会从 DisplayManager 获取最新的聚合结果
        if hasattr(self.chart_renderer, 'refresh_chart'):
            self.chart_renderer.refresh_chart()
        
        # 更新状态栏消息（如果有）
        if result.status_message and hasattr(self.chart_renderer, 'update_status'):
            self.chart_renderer.update_status(result.status_message)

    def clear_strategy_display(self, strategy_name: str) -> None:
        """清除指定策略的显示"""
        if hasattr(self.chart_renderer, 'refresh_chart'):
            self.chart_renderer.refresh_chart()

    def clear_all_displays(self) -> None:
        """清除所有策略显示"""
        if hasattr(self.chart_renderer, 'refresh_chart'):
            self.chart_renderer.refresh_chart()
