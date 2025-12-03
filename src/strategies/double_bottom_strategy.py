# strategies/double_bottom_strategy.py

from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import sqlite3

try:
    from ..data.data_loader import load_candles_from_sqlite
    HAS_DATA_LOADER = True
except Exception:
    HAS_DATA_LOADER = False
    load_candles_from_sqlite = None

try:
    from ..displays import DisplayResult
    HAS_DISPLAY = True
except Exception:
    DisplayResult = None
    HAS_DISPLAY = False

# 导入ZigZag分析器（用于辅助检测）
try:
    from .zigzag_wave_peaks_valleys import ZigZagAnalyzer
except ImportError:
    # 如果没有ZigZag模块，创建一个简化的版本
    class ZigZagAnalyzer:
        def __init__(self, candles, min_reversal=0.05):
            self.candles = candles
            self.min_reversal = min_reversal

        def find_significant_peaks_and_valleys(self, candles):
            # 简化的波峰波谷检测
            peaks = []
            valleys = []
            prices = [c['close'] for c in candles]

            for i in range(1, len(prices) - 1):
                if prices[i] > prices[i-1] and prices[i] > prices[i+1]:
                    peaks.append(i)
                elif prices[i] < prices[i-1] and prices[i] < prices[i+1]:
                    valleys.append(i)

            return peaks, valleys


class DoubleBottomAnalyzer:
    """双底形态检测器"""

    def __init__(self, candles: List[Dict[str, Any]], lookback_period: int = 100):
        """
        初始化双底形态分析器

        Args:
            candles: K线数据
            lookback_period: 回溯周期，用于判断"很长一段时间"
        """
        self.candles = candles
        self.lookback_period = lookback_period

    def find_double_bottom_patterns(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检测双底形态

        双底形态特征：
        1. 第一个波谷：很长一段时间的最低点
        2. 上涨到波峰：时间比较长的高点
        3. 下跌回到第一个波谷附近

        Returns:
            双底形态列表，每个包含形态信息
        """
        if len(candles) < self.lookback_period:
            return []

        patterns = []

        # 使用ZigZag算法先识别主要的波峰波谷
        zigzag_analyzer = ZigZagAnalyzer(candles, min_reversal=0.03)  # 3%的反转
        peaks, valleys = zigzag_analyzer.find_significant_peaks_and_valleys(candles)

        # 寻找双底形态
        used_valleys = set()  # 记录已使用的波谷索引，避免重复

        for i in range(len(valleys) - 1):
            if valleys[i] in used_valleys:
                continue

            valley1_idx = valleys[i]

            # 查找下一个波谷
            for j in range(i + 1, len(valleys)):
                if valleys[j] in used_valleys:
                    continue

                valley2_idx = valleys[j]

                # 检查两个波谷之间的距离是否足够（至少10根K线）
                if valley2_idx - valley1_idx < 10:
                    continue

                # 检查两个波谷是否在相似的价格水平
                valley1_price = candles[valley1_idx]['low']
                valley2_price = candles[valley2_idx]['low']

                # 价格差异不超过3%
                price_diff = abs(valley1_price - valley2_price) / valley1_price
                if price_diff > 0.03:
                    continue

                # 查找两个波谷之间的波峰（放宽条件，只要有显著的高点即可）
                peak_between = None
                max_height = max(candles[valley1_idx]['low'], candles[valley2_idx]['low'])

                # 首先尝试找到ZigZag识别的波峰
                for peak_idx in peaks:
                    if valley1_idx < peak_idx < valley2_idx:
                        current_height = candles[peak_idx]['high']
                        if current_height > max_height * 1.02:  # 至少比波谷高2%
                            if peak_between is None or current_height > candles[peak_between]['high']:
                                peak_between = peak_idx

                # 如果没有找到ZigZag波峰，尝试在价格区间中寻找局部高点
                if peak_between is None:
                    # 在两个波谷之间寻找价格最高的点
                    max_price = 0
                    max_price_idx = -1
                    for idx in range(valley1_idx + 1, valley2_idx):
                        if candles[idx]['high'] > max_price:
                            max_price = candles[idx]['high']
                            max_price_idx = idx

                    # 如果最高价足够高，标记为波峰
                    if max_price > max_height * 1.02:
                        peak_between = max_price_idx

                if peak_between is None:
                    continue

                # 验证第一个波谷是否是长时间最低点
                if not self._is_long_term_low(valley1_idx, candles):
                    continue

                # 验证中间波峰是否是相对高点
                if not self._is_significant_high(peak_between, valley1_idx, valley2_idx, candles):
                    continue

                # 计算形态的时间跨度
                time_span = valley2_idx - valley1_idx

                # 记录双底形态
                pattern = {
                    'valley1_idx': valley1_idx,
                    'peak_idx': peak_between,
                    'valley2_idx': valley2_idx,
                    'valley1_price': valley1_price,
                    'peak_price': candles[peak_between]['high'],
                    'valley2_price': valley2_price,
                    'time_span': time_span,
                    'neckline_price': max(valley1_price, valley2_price) * 1.02,  # 颈线位置
                }

                patterns.append(pattern)

                # 标记已使用的波谷，避免重复检测
                used_valleys.add(valley1_idx)
                used_valleys.add(valley2_idx)
                break  # 找到一个有效的双底后，继续下一个波谷

        # 过滤掉相交的模式，只保留包含关系
        patterns = self._resolve_partial_intersections(patterns)

        return patterns

    def find_patterns(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检测双底形态（别名方法，用于统一接口）

        Returns:
            双底形态列表
        """
        return self.find_double_bottom_patterns(candles)

    def _is_long_term_low(self, valley_idx: int, candles: List[Dict[str, Any]]) -> bool:
        """检查是否是长时间的最低点"""
        if valley_idx < self.lookback_period // 2:
            return False

        valley_price = candles[valley_idx]['low']

        # 检查前面的K线是否有更低的价格
        start_idx = max(0, valley_idx - self.lookback_period)
        for i in range(start_idx, valley_idx):
            if candles[i]['low'] < valley_price * 0.98:  # 允许2%的误差
                return False

        return True

    def _is_significant_high(self, peak_idx: int, valley1_idx: int, valley2_idx: int,
                           candles: List[Dict[str, Any]]) -> bool:
        """检查波峰是否足够显著"""
        peak_price = candles[peak_idx]['high']

        # 波峰应该比两个波谷高出至少2%
        avg_valley_price = (candles[valley1_idx]['low'] + candles[valley2_idx]['low']) / 2
        if peak_price < avg_valley_price * 1.02:
            return False

        # 检查波峰是否是相对高点（在一定范围内）
        window_size = min(5, peak_idx - valley1_idx, valley2_idx - peak_idx)
        if window_size < 2:
            return True  # 如果窗口太小，认为是显著的

        # 检查周围点是否都低于波峰
        for i in range(max(valley1_idx, peak_idx - window_size), min(valley2_idx, peak_idx + window_size + 1)):
            if i != peak_idx and candles[i]['high'] > peak_price * 0.98:
                return False

        return True

    def _resolve_partial_intersections(self, patterns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        过滤掉相交的模式，只保留包含关系。
        大的模式可以包含小的模式，但不能有相交（部分重叠但不完全包含）。
        """
        if len(patterns) <= 1:
            return patterns

        # 按时间跨度排序（大的在前）
        patterns_sorted = sorted(patterns, key=lambda p: p['time_span'], reverse=True)

        filtered_patterns = []

        for pattern in patterns_sorted:
            # 检查当前模式是否与已保留的模式相交
            is_valid = True
            for existing in filtered_patterns:
                if self._patterns_intersect(pattern, existing):
                    is_valid = False
                    break

            if is_valid:
                filtered_patterns.append(pattern)

        return filtered_patterns

    def _patterns_intersect(self, pattern1: Dict[str, Any], pattern2: Dict[str, Any]) -> bool:
        """
        检查两个模式是否相交（部分重叠但不完全包含）。
        如果完全包含，则不认为是相交（允许包含关系）。
        """
        start1 = pattern1['valley1_idx']
        end1 = pattern1['valley2_idx']
        start2 = pattern2['valley1_idx']
        end2 = pattern2['valley2_idx']

        # 检查是否完全包含
        pattern1_contains_pattern2 = start1 <= start2 and end1 >= end2
        pattern2_contains_pattern1 = start2 <= start1 and end2 >= end1

        if pattern1_contains_pattern2 or pattern2_contains_pattern1:
            return False  # 允许包含关系

        # 检查是否相交（重叠但不完全包含）
        return max(start1, start2) < min(end1, end2)

    def generate_markers(self, patterns: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        生成双底形态标记（别名方法，用于统一接口）

        Returns:
            标记列表
        """
        """生成双底形态标记 - 为每个形态使用不同的颜色组"""
        markers = []

        # 为不同形态定义不同的颜色方案（每个形态使用一组颜色）
        color_schemes = [
            {'valley': '#00AA00', 'peak': '#FF0000', 'name': '1'},  # 绿色谷，红色峰
            {'valley': '#0088FF', 'peak': '#FF8800', 'name': '2'},  # 蓝色谷，橙色峰
            {'valley': '#AA00AA', 'peak': '#FFAA00', 'name': '3'},  # 紫色谷，黄色峰
            {'valley': '#00AAAA', 'peak': '#FF0088', 'name': '4'},  # 青色谷，粉色峰
            {'valley': '#88AA00', 'peak': '#AA0088', 'name': '5'},  # 橄榄色谷，紫红色峰
        ]

        for i, pattern in enumerate(patterns):
            # 为每个形态选择颜色方案
            color_scheme = color_schemes[i % len(color_schemes)]

            # 标记第一个波谷
            valley1_marker = {
                'id': f'pattern_scanner_double_bottom_{i+1}_valley1',
                'time': candles[pattern['valley1_idx']]['time'],
                'position': 'belowBar',
                'color': color_scheme['valley'],
                'shape': 'arrowDown',
                'text': f'形态扫描器-双底{color_scheme["name"]}谷1 {pattern["valley1_price"]:.2f}',
            }

            # 标记波峰
            peak_marker = {
                'id': f'pattern_scanner_double_bottom_{i+1}_peak',
                'time': candles[pattern['peak_idx']]['time'],
                'position': 'aboveBar',
                'color': color_scheme['peak'],
                'shape': 'arrowUp',
                'text': f'形态扫描器-双底{color_scheme["name"]}峰 {pattern["peak_price"]:.2f}',
            }

            # 标记第二个波谷
            valley2_marker = {
                'id': f'pattern_scanner_double_bottom_{i+1}_valley2',
                'time': candles[pattern['valley2_idx']]['time'],
                'position': 'belowBar',
                'color': color_scheme['valley'],
                'shape': 'arrowDown',
                'text': f'形态扫描器-双底{color_scheme["name"]}谷2 {pattern["valley2_price"]:.2f}',
            }

            markers.extend([valley1_marker, peak_marker, valley2_marker])

        return markers


class DoubleBottomStrategy:
    """双底形态选股策略"""

    def __init__(self):
        if not HAS_DATA_LOADER:
            raise ImportError("缺少 data_loader 模块")

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional[Any]:
        """
        扫描当前股票的双底形态

        Args:
            db_path: 数据库路径
            table_name: 表名

        Returns:
            包含标记和状态信息的字典
        """
        # 加载股票数据
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"无法加载股票 {table_name} 的数据")

        candles, volumes, instrument = data

        # 执行双底形态检测
        analyzer = DoubleBottomAnalyzer(candles)
        patterns = analyzer.find_double_bottom_patterns(candles)

        # 生成标记
        markers = analyzer.generate_markers(patterns, candles)

        # 统计信息
        pattern_count = len(patterns)

        if pattern_count > 0:
            status_message = f"双底形态检测完成，发现 {pattern_count} 个双底形态"
        else:
            status_message = "双底形态检测完成，未发现显著的双底形态"

        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name="double_bottom",
                markers=markers,
                status_message=status_message
            )
        else:
            return {
                "strategy_name": "double_bottom",
                "markers": markers,
                "status_message": status_message,
            }