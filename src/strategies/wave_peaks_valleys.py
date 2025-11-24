# strategies/wave_peaks_valleys.py

from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING
from pathlib import Path
import sqlite3

try:
    from ..data.data_loader import load_candles_from_sqlite
    HAS_DATA_LOADER = True
except Exception:
    HAS_DATA_LOADER = False
    load_candles_from_sqlite = None

if TYPE_CHECKING:
    from ..displays import DisplayResult
else:
    try:
        from ..displays import DisplayResult
        HAS_DISPLAY = True
    except Exception:
        DisplayResult = None
        HAS_DISPLAY = False


class WaveAnalyzer:
    """波峰波谷检测器"""

    def __init__(self, candles: List[Dict[str, Any]]):
        self.candles = candles

    def find_significant_peaks_and_valleys(self, candles: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
        """寻找重要的波峰和波谷 - 基于局部极值的检测"""
        peaks = []
        valleys = []

        if len(candles) < 20:
            return peaks, valleys

        # 使用局部极值检测算法
        peaks, valleys = self._find_local_extrema(candles, window=5)

        return peaks, valleys

    def _find_local_extrema(self, candles: List[Dict[str, Any]], window: int = 5) -> Tuple[List[int], List[int]]:
        """寻找局部极值点（波峰和波谷）- 增强版，包含趋势确认"""
        peaks = []
        valleys = []

        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        for i in range(window, len(candles) - window):
            # 检查是否为局部最高点（波峰）- 使用最高价
            is_local_peak = True
            for j in range(i - window, i + window + 1):
                if j != i and highs[j] >= highs[i]:
                    is_local_peak = False
                    break

            if is_local_peak:
                # 趋势确认：检查波峰后价格是否确实下跌
                if self._confirm_peak_trend_change(candles, i):
                    peaks.append(i)
                continue

            # 检查是否为局部最低点（波谷）- 使用最低价
            is_local_valley = True
            for j in range(i - window, i + window + 1):
                if j != i and lows[j] <= lows[i]:
                    is_local_valley = False
                    break

            if is_local_valley:
                # 趋势确认：检查波谷后价格是否确实上涨
                if self._confirm_valley_trend_change(candles, i):
                    valleys.append(i)

        # 添加对短期剧烈波动的额外检测
        short_term_peaks, short_term_valleys = self._detect_short_term_volatility(candles)
        peaks.extend(short_term_peaks)
        valleys.extend(short_term_valleys)

        # 过滤掉太接近的点，保持最小距离 - 降低最小距离以检测短期波动
        peaks = self._filter_close_points(peaks, min_distance=15)  # 从15降低到12
        valleys = self._filter_close_points(valleys, min_distance=15)  # 从15降低到12

        # 确保波峰波谷交替出现
        peaks, valleys = self._ensure_alternating_peaks_valleys(peaks, valleys, highs, lows)

        return peaks, valleys

    def _confirm_peak_trend_change(self, candles: List[Dict[str, Any]], peak_idx: int,
                                  confirmation_period: int = 10) -> bool:
        """确认波峰后趋势是否确实发生变化（下跌）"""
        if peak_idx + confirmation_period >= len(candles):
            return False

        # 使用波峰的最高价作为基准
        peak_price = candles[peak_idx]['high']
        future_prices = [c['high'] for c in candles[peak_idx + 1: peak_idx + confirmation_period + 1]]

        # 检查是否有足够幅度的下跌（相对于最高价）
        min_future_price = min(future_prices)
        decline_pct = (peak_price - min_future_price) / peak_price

        # 下跌幅度至少要超过1.2% (从1.5%降低到1.2%)
        return decline_pct >= 0.012

    def _confirm_valley_trend_change(self, candles: List[Dict[str, Any]], valley_idx: int,
                                    confirmation_period: int = 10) -> bool:
        """确认波谷后趋势是否确实发生变化（上涨）"""
        if valley_idx + confirmation_period >= len(candles):
            return False

        # 使用波谷的最低价作为基准
        valley_price = candles[valley_idx]['low']
        future_prices = [c['low'] for c in candles[valley_idx + 1: valley_idx + confirmation_period + 1]]

        # 检查是否有足够幅度的上涨（相对于最低价）
        max_future_price = max(future_prices)
        rise_pct = (max_future_price - valley_price) / valley_price

        # 上涨幅度至少要超过1.2% (从1.5%降低到1.2%)
        return rise_pct >= 0.012

    def _filter_close_points(self, points: List[int], min_distance: int) -> List[int]:
        """过滤掉距离太近的点"""
        if not points:
            return points

        filtered = [points[0]]
        for point in points[1:]:
            if point - filtered[-1] >= min_distance:
                filtered.append(point)

        return filtered

    def _ensure_alternating_peaks_valleys(self, peaks: List[int], valleys: List[int],
                                        highs: List[float], lows: List[float]) -> Tuple[List[int], List[int]]:
        """确保波峰波谷交替出现，形成完整的波浪结构"""
        # 合并所有极值点
        all_points = []
        for idx in peaks:
            all_points.append(('peak', idx, highs[idx]))  # 使用最高价作为波峰值
        for idx in valleys:
            all_points.append(('valley', idx, lows[idx]))  # 使用最低价作为波谷值

        # 按时间顺序排序
        all_points.sort(key=lambda x: x[1])

        # 移除连续相同类型的点，保持交替
        filtered_points = []
        prev_type = None

        for point_type, idx, price in all_points:
            if prev_type != point_type:
                filtered_points.append((point_type, idx, price))
                prev_type = point_type
            else:
                # 如果连续两个相同类型，保留价格更极端的那个
                if filtered_points:
                    last_type, last_idx, last_price = filtered_points[-1]
                    if point_type == 'peak' and price > last_price:
                        filtered_points[-1] = (point_type, idx, price)
                    elif point_type == 'valley' and price < last_price:
                        filtered_points[-1] = (point_type, idx, price)

        # 分离波峰和波谷
        final_peaks = [idx for pt, idx, p in filtered_points if pt == 'peak']
        final_valleys = [idx for pt, idx, p in filtered_points if pt == 'valley']

        return final_peaks, final_valleys

    def _detect_short_term_volatility(self, candles: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
        """检测短期剧烈波动（几天内的暴涨暴跌）"""
        peaks = []
        valleys = []

        if len(candles) < 15:  # 需要更多数据
            return peaks, valleys

        for i in range(5, len(candles) - 5):  # 扩大边界检查
            current_high = candles[i]['high']
            current_low = candles[i]['low']

            # 检查短期内的剧烈波动
            # 向前5天和向后5天的价格范围
            prev_prices = [c['high'] for c in candles[max(0, i-5):i]]
            next_prices = [c['high'] for c in candles[i+1:min(len(candles), i+6)]]

            prev_lows = [c['low'] for c in candles[max(0, i-5):i]]
            next_lows = [c['low'] for c in candles[i+1:min(len(candles), i+6)]]

            # 检测短期波峰：当前价格显著高于前后价格
            if prev_prices and next_prices:
                prev_max = max(prev_prices)
                next_max = max(next_prices)
                if current_high > prev_max * 1.05 and current_high > next_max * 1.05:  # 提高到5%
                    # 检查是否有至少2%的下跌确认
                    if self._confirm_peak_trend_change(candles, i, confirmation_period=8):
                        peaks.append(i)

            # 检测短期波谷：当前价格显著低于前后价格
            if prev_lows and next_lows:
                prev_min = min(prev_lows)
                next_min = min(next_lows)
                if current_low < prev_min * 0.95 and current_low < next_min * 0.95:  # 提高到5%
                    # 检查是否有至少2%的上涨确认
                    if self._confirm_valley_trend_change(candles, i, confirmation_period=8):
                        valleys.append(i)

        return peaks, valleys

    def generate_wave_markers(self, peaks: List[int], valleys: List[int],
                            candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成波峰波谷标记"""
        markers = []
        marker_id = 0

        # 添加波峰标记
        for idx in peaks:
            if idx < len(candles):
                candle = candles[idx]
                markers.append({
                    "id": f"peak_{marker_id}",
                    "time": candle['time'],
                    "position": "aboveBar",  # 与波谷一样，都在K线上方显示
                    "color": "#ff4444",
                    "shape": "arrowUp",
                    "text": f"波峰 {candle['high']:.2f}"
                })
                marker_id += 1

        # 添加波谷标记
        for idx in valleys:
            if idx < len(candles):
                candle = candles[idx]
                markers.append({
                    "id": f"valley_{marker_id}",
                    "time": candle['time'],
                    "position": "aboveBar",  # 改为aboveBar，在K线上方显示
                    "color": "#44ff44",
                    "shape": "arrowDown",
                    "text": f"波谷 {candle['low']:.2f}"
                })
                marker_id += 1

        return markers


class WavePeaksValleysStrategy:
    """波峰波谷检测策略"""

    def __init__(self):
        if not HAS_DATA_LOADER:
            raise ImportError("缺少 data_loader 模块")

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional['DisplayResult']:
        """
        扫描当前股票的波峰波谷

        Args:
            db_path: 数据库路径
            table_name: 表名

        Returns:
            显示结果，包含波峰波谷标记
        """
        # 加载股票数据
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"无法加载股票 {table_name} 的数据")

        candles, volumes, instrument = data

        # 执行波峰波谷检测
        markers = self.analyze_wave_peaks_valleys(candles)

        if not markers:
            return None

        # 统计信息
        peak_count = sum(1 for m in markers if "波峰" in m["text"])
        valley_count = sum(1 for m in markers if "波谷" in m["text"])

        status_message = f"检测到 {peak_count} 个波峰，{valley_count} 个波谷"

        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name="wave_peaks_valleys",
                markers=markers,
                status_message=status_message
            )
        else:
            # 如果没有DisplayResult类，返回简单的字典
            return {
                "strategy_name": "wave_peaks_valleys",
                "markers": markers,
                "status_message": status_message
            }

    def analyze_wave_peaks_valleys(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分析股票的波峰波谷，返回标记列表

        Args:
            candles: K线数据

        Returns:
            波峰波谷标记列表
        """
        if not candles or len(candles) < 20:
            return []

        # 创建波浪分析器
        analyzer = WaveAnalyzer(candles)

        # 寻找波峰和波谷
        peaks, valleys = analyzer.find_significant_peaks_and_valleys(candles)

        # 生成标记
        markers = analyzer.generate_wave_markers(peaks, valleys, candles)

        return markers