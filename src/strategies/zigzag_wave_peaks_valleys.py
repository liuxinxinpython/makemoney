# strategies/zigzag_wave_peaks_valleys.py

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


class ZigZagAnalyzer:
    """ZigZag波峰波谷检测器"""

    def __init__(self, candles: List[Dict[str, Any]], min_reversal: float = 0.05):
        """
        初始化ZigZag分析器

        Args:
            candles: K线数据
            min_reversal: 最小反转百分比 (默认5%)
        """
        self.candles = candles
        self.min_reversal = min_reversal

    def find_significant_peaks_and_valleys(self, candles: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
        """
        使用ZigZag算法检测波峰和波谷

        ZigZag算法：
        1. 从左到右扫描价格
        2. 当价格上涨超过最小反转百分比时，记录波谷
        3. 当价格下跌超过最小反转百分比时，记录波峰
        4. 持续这个过程，过滤掉小幅波动
        """
        if len(candles) < 3:
            return [], []

        peaks = []
        valleys = []

        # 使用收盘价作为基准
        prices = [c['close'] for c in candles]

        # ZigZag算法实现
        trend = 0  # 0=未确定, 1=上涨, -1=下跌
        last_pivot_price = prices[0]
        last_pivot_idx = 0

        for i in range(1, len(prices)):
            current_price = prices[i]

            if trend == 0:
                # 初始趋势判断
                change_pct = abs(current_price - last_pivot_price) / last_pivot_price
                if change_pct >= self.min_reversal:
                    if current_price > last_pivot_price:
                        trend = 1  # 开始上涨
                        valleys.append(last_pivot_idx)
                    else:
                        trend = -1  # 开始下跌
                        peaks.append(last_pivot_idx)
                    last_pivot_price = current_price
                    last_pivot_idx = i

            elif trend == 1:
                # 正在上涨趋势中
                if current_price > last_pivot_price:
                    # 继续上涨，更新pivot
                    last_pivot_price = current_price
                    last_pivot_idx = i
                else:
                    # 可能开始下跌
                    change_pct = (last_pivot_price - current_price) / last_pivot_price
                    if change_pct >= self.min_reversal:
                        # 确认反转，记录波峰
                        peaks.append(last_pivot_idx)
                        trend = -1
                        last_pivot_price = current_price
                        last_pivot_idx = i

            elif trend == -1:
                # 正在下跌趋势中
                if current_price < last_pivot_price:
                    # 继续下跌，更新pivot
                    last_pivot_price = current_price
                    last_pivot_idx = i
                else:
                    # 可能开始上涨
                    change_pct = (current_price - last_pivot_price) / last_pivot_price
                    if change_pct >= self.min_reversal:
                        # 确认反转，记录波谷
                        valleys.append(last_pivot_idx)
                        trend = 1
                        last_pivot_price = current_price
                        last_pivot_idx = i

        # 处理最后一个pivot点
        if trend == 1 and last_pivot_idx != len(candles) - 1:
            peaks.append(last_pivot_idx)
        elif trend == -1 and last_pivot_idx != len(candles) - 1:
            valleys.append(last_pivot_idx)

        # 过滤掉过于密集的点（最小距离5根K线）
        peaks = self._filter_close_points(peaks, 5)
        valleys = self._filter_close_points(valleys, 5)

        print(f"ZigZag detection: found {len(peaks)} peaks and {len(valleys)} valleys with {self.min_reversal*100}% reversal")

        return peaks, valleys

    def _filter_close_points(self, points: List[int], min_distance: int) -> List[int]:
        """过滤掉距离太近的点"""
        if not points:
            return points

        filtered = [points[0]]
        for point in points[1:]:
            if point - filtered[-1] >= min_distance:
                filtered.append(point)

        return filtered

    def generate_wave_markers(self, peaks: List[int], valleys: List[int],
                            candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成ZigZag波峰波谷标记"""
        markers: List[Dict[str, Any]] = []
        marker_id = 0

        # 添加波峰标记
        for idx in peaks:
            if 0 <= idx < len(candles):
                c = candles[idx]
                markers.append({
                    'id': f'zigzag_peak_{marker_id}',
                    'time': c['time'],
                    'position': 'aboveBar',
                    'color': '#ff4444',
                    'shape': 'arrowUp',
                    'text': f'ZZ波峰 {c["high"]:.2f}',
                })
                marker_id += 1

        # 添加波谷标记
        for idx in valleys:
            if 0 <= idx < len(candles):
                c = candles[idx]
                markers.append({
                    'id': f'zigzag_valley_{marker_id}',
                    'time': c['time'],
                    'position': 'aboveBar',
                    'color': '#44ff44',
                    'shape': 'arrowDown',
                    'text': f'ZZ波谷 {c["low"]:.2f}',
                })
                marker_id += 1

        # 按时间降序排序（最新的在前），限制为300个
        if len(markers) > 300:
            markers = sorted(markers, key=lambda m: m['time'], reverse=True)[:300]

        return markers


class ZigZagWavePeaksValleysStrategy:
    """ZigZag波峰波谷检测策略"""

    def __init__(self, min_reversal: float = 0.05):
        """
        初始化ZigZag策略

        Args:
            min_reversal: 最小反转百分比 (默认5%)
        """
        if not HAS_DATA_LOADER:
            raise ImportError("缺少 data_loader 模块")
        self.min_reversal = min_reversal

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional[Any]:
        """
        扫描当前股票的ZigZag波峰波谷

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

        # 执行ZigZag波峰波谷检测
        analyzer = ZigZagAnalyzer(candles, self.min_reversal)
        peaks, valleys = analyzer.find_significant_peaks_and_valleys(candles)

        # 生成标记
        markers = analyzer.generate_wave_markers(peaks, valleys, candles)

        # 统计信息
        peak_count = sum(1 for m in markers if "ZZ波峰" in m["text"])
        valley_count = sum(1 for m in markers if "ZZ波谷" in m["text"])

        status_message = f"ZigZag算法检测到 {peak_count} 个波峰，{valley_count} 个波谷"

        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name="zigzag_wave_peaks_valleys",
                markers=markers,
                status_message=status_message
            )
        else:
            return {
                "strategy_name": "zigzag_wave_peaks_valleys",
                "markers": markers,
                "status_message": status_message,
            }