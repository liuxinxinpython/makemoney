# displays/chart_display.py

from typing import List, Dict, Any, Optional
from .base import DisplayInterface, DisplayResult


class ChartDisplay(DisplayInterface):
    """TradingView图表显示器"""

    def __init__(self, chart_renderer):
        """
        Args:
            chart_renderer: 图表渲染器对象，应该有render_chart方法
        """
        self.chart_renderer = chart_renderer
        self._strategy_results: Dict[str, DisplayResult] = {}

    def display_result(self, result: DisplayResult) -> None:
        """显示策略结果到图表"""
        # 存储策略结果
        self._strategy_results[result.strategy_name] = result

        # 重新渲染图表
        self._render_combined_chart()

        # 更新状态栏消息（如果有）
        if result.status_message and hasattr(self.chart_renderer, 'update_status'):
            self.chart_renderer.update_status(result.status_message)

    def clear_strategy_display(self, strategy_name: str) -> None:
        """清除指定策略的显示"""
        if strategy_name in self._strategy_results:
            del self._strategy_results[strategy_name]
            self._render_combined_chart()

    def clear_all_displays(self) -> None:
        """清除所有策略显示"""
        self._strategy_results.clear()
        self._render_combined_chart()

    def _render_combined_chart(self) -> None:
        """合并所有活跃策略的结果并渲染图表"""
        # 合并所有策略的markers
        combined_markers = []
        combined_overlays = []
        combined_annotations = []

        for result in self._strategy_results.values():
            combined_markers.extend(result.markers or [])
            combined_overlays.extend(result.overlays or [])
            combined_annotations.extend(result.annotations or [])

        # 调用图表渲染器
        if hasattr(self.chart_renderer, 'render_chart_with_displays'):
            self.chart_renderer.render_chart_with_displays(
                markers=combined_markers,
                overlays=combined_overlays,
                annotations=combined_annotations
            )
        elif hasattr(self.chart_renderer, '_render_chart'):
            # 使用main_ui的_render_chart方法，需要获取成交量数据
            volumes = []
            instrument = None
            if hasattr(self.chart_renderer, 'current_volumes'):
                volumes = self.chart_renderer.current_volumes
            if hasattr(self.chart_renderer, 'current_instrument'):
                instrument = self.chart_renderer.current_instrument

            self.chart_renderer._render_chart(
                self.chart_renderer.current_candles,
                volumes,  # 正确传递成交量数据
                instrument,  # 正确传递instrument信息
                combined_markers,
                combined_overlays
            )
        else:
            # 回退到标准渲染方法
            self._render_fallback(combined_markers, combined_overlays, combined_annotations)

    def _render_fallback(self, markers: List[Dict[str, Any]],
                        overlays: List[Dict[str, Any]],
                        annotations: List[Dict[str, Any]]) -> None:
        """回退渲染方法"""
        # 这里应该调用实际的图表渲染逻辑
        # 由于我们不知道具体的渲染器接口，这里只是占位符
        print(f"Rendering chart with {len(markers)} markers, {len(overlays)} overlays, {len(annotations)} annotations")

    def get_strategy_results(self) -> Dict[str, DisplayResult]:
        """获取当前活跃的策略结果"""
        return self._strategy_results.copy()

    def has_active_displays(self) -> bool:
        """检查是否有活跃的显示"""
        return len(self._strategy_results) > 0