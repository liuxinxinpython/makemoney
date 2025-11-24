# strategies/advanced_wave_peaks_valleys.py

from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import sqlite3
import numpy as np
from scipy import signal
from scipy.ndimage import morphology

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


class AdvancedWaveAnalyzer:
    """高级波峰波谷检测器 - 基于开源算法的优化版本"""

    def __init__(self, candles: List[Dict[str, Any]]):
        self.candles = candles
        self.prices = np.array([c['close'] for c in candles])
        self.highs = np.array([c['high'] for c in candles])
        self.lows = np.array([c['low'] for c in candles])
        self.volumes = np.array([c.get('volume', 0) for c in candles])

        # 计算自适应参数
        self.volatility = self._calculate_volatility()
        self.adaptive_window = self._calculate_adaptive_window()
        self.significance_threshold = self._calculate_significance_threshold()

    def _calculate_volatility(self) -> float:
        """计算价格波动率"""
        if len(self.prices) < 2:
            return 0.0

        returns = np.diff(np.log(self.prices))
        return np.std(returns) * np.sqrt(252)  # 年化波动率

    def _calculate_adaptive_window(self) -> int:
        """根据波动率计算自适应窗口大小"""
        base_window = 15
        if self.volatility > 0.5:  # 高波动
            return max(5, base_window // 2)
        elif self.volatility < 0.2:  # 低波动
            return min(30, base_window * 2)
        else:
            return base_window

    def _calculate_significance_threshold(self) -> float:
        """计算统计显著性阈值"""
        if len(self.prices) < 10:
            return 0.001

        # 使用MAD (Median Absolute Deviation) 作为鲁棒性度量
        median_price = np.median(self.prices)
        mad = np.median(np.abs(self.prices - median_price))
        return max(0.001, mad * 0.1)  # 至少0.1%的显著性

    def find_significant_peaks_and_valleys(self, candles: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
        """
        寻找显著的波峰和波谷 - 优化版本
        使用自适应参数、多尺度分析和成交量确认
        """
        if len(candles) < 50:
            return [], []

        # 使用自适应窗口进行Savitzky-Golay平滑
        smoothed_prices = self._savitzky_golay_smooth(candles, self.adaptive_window)

        # 多尺度分析：使用不同窗口大小检测
        scales = [self.adaptive_window // 2, self.adaptive_window, self.adaptive_window * 2]
        all_peaks = []
        all_valleys = []

        for scale in scales:
            if scale >= 5 and scale < len(smoothed_prices):
                peaks_scale, valleys_scale = self._morphological_peak_detection(smoothed_prices, scale)
                all_peaks.extend(peaks_scale)
                all_valleys.extend(valleys_scale)

        # 去重
        peaks = sorted(list(set(all_peaks)))
        valleys = sorted(list(set(all_valleys)))

        # 计算导数用于验证
        first_derivative = self._calculate_derivative(smoothed_prices)
        second_derivative = self._calculate_derivative(first_derivative)

        # 使用导数验证峰谷
        peaks_verified = self._verify_peaks_with_derivatives(peaks, first_derivative, second_derivative)
        valleys_verified = self._verify_valleys_with_derivatives(valleys, first_derivative, second_derivative)

        # 合并验证结果
        final_peaks = sorted(list(set(peaks_verified)))
        final_valleys = sorted(list(set(valleys_verified)))

        # 应用统计显著性过滤
        final_peaks = self._filter_by_significance(final_peaks, smoothed_prices, 'peak')
        final_valleys = self._filter_by_significance(final_valleys, smoothed_prices, 'valley')

        # 成交量确认
        final_peaks = self._confirm_with_volume(final_peaks, 'peak')
        final_valleys = self._confirm_with_volume(final_valleys, 'valley')

        # 趋势分析过滤
        final_peaks, final_valleys = self._filter_by_trend(final_peaks, final_valleys, smoothed_prices)

        # 确保交替出现
        final_peaks, final_valleys = self._ensure_alternating_peaks_valleys(final_peaks, final_valleys, smoothed_prices)

        return final_peaks, final_valleys

    def _savitzky_golay_smooth(self, candles: List[Dict[str, Any]], window_length: int = 15, polyorder: int = 3) -> np.ndarray:
        """使用Savitzky-Golay滤波器平滑价格数据"""
        # 提取收盘价
        prices = np.array([c['close'] for c in candles])

        # 确保窗口长度是奇数且不超过数据长度
        window_length = min(window_length, len(prices) if len(prices) % 2 == 1 else len(prices) - 1)
        if window_length < 5:
            window_length = 5

        # 应用Savitzky-Golay滤波器
        smoothed = signal.savgol_filter(prices, window_length, polyorder)
        return smoothed

    def _calculate_derivative(self, data: np.ndarray) -> np.ndarray:
        """计算数值导数"""
        return np.gradient(data)

    def _morphological_peak_detection(self, data: np.ndarray, min_distance: int = 5) -> Tuple[List[int], List[int]]:
        """使用简化的局部极值检测"""
        peaks = []
        valleys = []

        # 简化为基本的局部极值检测
        for i in range(min_distance, len(data) - min_distance):
            # 检查是否为局部最大值
            is_peak = True
            for j in range(i - min_distance, i + min_distance + 1):
                if j != i and data[j] >= data[i]:
                    is_peak = False
                    break
            if is_peak:
                peaks.append(i)

            # 检查是否为局部最小值
            is_valley = True
            for j in range(i - min_distance, i + min_distance + 1):
                if j != i and data[j] <= data[i]:
                    is_valley = False
                    break
            if is_valley:
                valleys.append(i)

        return peaks, valleys

    def _filter_by_significance(self, points: List[int], prices: np.ndarray, point_type: str) -> List[int]:
        """根据统计显著性过滤峰谷点"""
        if not points:
            return points

        significant_points = []
        for idx in points:
            if idx < len(prices):
                price = prices[idx]
                # 计算相对于局部区域的显著性
                window_size = min(20, len(prices) // 10)
                start_idx = max(0, idx - window_size)
                end_idx = min(len(prices), idx + window_size + 1)

                local_prices = prices[start_idx:end_idx]
                local_mean = np.mean(local_prices)
                local_std = np.std(local_prices)

                if local_std > 0:
                    z_score = abs(price - local_mean) / local_std
                    # 显著性阈值：至少0.5个标准差（进一步放宽要求）
                    if z_score >= 0.5:
                        significant_points.append(idx)

        return significant_points

    def _confirm_with_volume(self, points: List[int], point_type: str) -> List[int]:
        """使用成交量确认峰谷点"""
        if not points:
            return points

        confirmed_points = []
        for idx in points:
            if idx < len(self.volumes):
                volume = self.volumes[idx]
                # 计算局部平均成交量
                window_size = min(10, len(self.volumes) // 20)
                start_idx = max(0, idx - window_size)
                end_idx = min(len(self.volumes), idx + window_size + 1)

                local_volumes = self.volumes[start_idx:end_idx]
                avg_volume = np.mean(local_volumes)

                # 成交量确认：峰谷点处的成交量应该相对较高
                if volume >= avg_volume * 0.5:  # 至少50%的平均成交量（放宽要求）
                    confirmed_points.append(idx)

        return confirmed_points

    def _filter_by_trend(self, peaks: List[int], valleys: List[int], prices: np.ndarray) -> Tuple[List[int], List[int]]:
        """根据趋势过滤峰谷点，避免在单边行情中误检"""
        if not peaks and not valleys:
            return peaks, valleys

        # 计算长期趋势
        if len(prices) > 50:
            long_trend = np.polyfit(range(len(prices)), prices, 1)[0]
        else:
            long_trend = 0

        filtered_peaks = []
        filtered_valleys = []

        # 在上升趋势中，更严格验证波谷
        if long_trend > 0:
            # 保留显著的波峰
            filtered_peaks = peaks
            # 只保留深度足够的波谷
            for valley_idx in valleys:
                if valley_idx < len(prices):
                    valley_price = prices[valley_idx]
                    # 计算从最近波峰到这个波谷的跌幅
                    recent_peaks = [p for p in peaks if p < valley_idx]
                    if recent_peaks:
                        recent_peak_price = prices[max(recent_peaks)]
                        drop_pct = (recent_peak_price - valley_price) / recent_peak_price
                        if drop_pct >= 0.02:  # 至少2%的跌幅（放宽要求）
                            filtered_valleys.append(valley_idx)
        # 在下降趋势中，更严格验证波峰
        elif long_trend < 0:
            # 只保留显著的波峰
            for peak_idx in peaks:
                if peak_idx < len(prices):
                    peak_price = prices[peak_idx]
                    # 计算从最近波谷到这个波峰的涨幅
                    recent_valleys = [v for v in valleys if v < peak_idx]
                    if recent_valleys:
                        recent_valley_price = prices[max(recent_valleys)]
                        rise_pct = (peak_price - recent_valley_price) / recent_valley_price
                        if rise_pct >= 0.02:  # 至少2%的涨幅（放宽要求）
                            filtered_peaks.append(peak_idx)
            filtered_valleys = valleys
        else:
            # 震荡行情，保留所有点
            filtered_peaks = peaks
            filtered_valleys = valleys

        return filtered_peaks, filtered_valleys

    def _verify_peaks_with_derivatives(self, candidate_peaks: List[int],
                                     first_deriv: np.ndarray,
                                     second_deriv: np.ndarray) -> List[int]:
        """使用导数信息验证峰值"""
        verified_peaks = []

        for peak_idx in candidate_peaks:
            if peak_idx <= 0 or peak_idx >= len(first_deriv) - 1:
                continue

            # 峰值处一阶导数应接近零且二阶导数为负
            if (abs(first_deriv[peak_idx]) < abs(first_deriv).std() * 0.5 and
                second_deriv[peak_idx] < 0):
                verified_peaks.append(peak_idx)

        return verified_peaks

    def _verify_valleys_with_derivatives(self, candidate_valleys: List[int],
                                       first_deriv: np.ndarray,
                                       second_deriv: np.ndarray) -> List[int]:
        """使用导数信息验证谷值"""
        verified_valleys = []

        for valley_idx in candidate_valleys:
            if valley_idx <= 0 or valley_idx >= len(first_deriv) - 1:
                continue

            # 谷值处一阶导数应接近零且二阶导数为正
            if (abs(first_deriv[valley_idx]) < abs(first_deriv).std() * 0.5 and
                second_deriv[valley_idx] > 0):
                verified_valleys.append(valley_idx)

        return verified_valleys

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
                                        prices: np.ndarray) -> Tuple[List[int], List[int]]:
        """确保波峰波谷交替出现，形成完整的波浪结构"""
        # 合并所有极值点
        all_points = []
        for idx in peaks:
            all_points.append(('peak', idx, prices[idx]))
        for idx in valleys:
            all_points.append(('valley', idx, prices[idx]))

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

    def generate_wave_markers(self, peaks: List[int], valleys: List[int],
                            candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成波峰波谷标记 - 高级版本使用不同颜色表示检测方法"""
        markers = []
        marker_id = 0

        # 添加波峰标记 - 使用橙色表示高级检测
        for idx in peaks:
            if idx < len(candles):
                candle = candles[idx]
                markers.append({
                    "id": f"advanced_peak_{marker_id}",
                    "time": candle['time'],
                    "position": "aboveBar",
                    "color": "#ff8c00",  # 深橙色
                    "shape": "arrowUp",
                    "text": f"高级波峰 {candle['high']:.2f}",
                    "size": 1.5  # 更大的标记
                })
                marker_id += 1

        # 添加波谷标记 - 使用紫色表示高级检测
        for idx in valleys:
            if idx < len(candles):
                candle = candles[idx]
                markers.append({
                    "id": f"advanced_valley_{marker_id}",
                    "time": candle['time'],
                    "position": "aboveBar",
                    "color": "#8a2be2",  # 蓝紫色
                    "shape": "arrowDown",
                    "text": f"高级波谷 {candle['low']:.2f}",
                    "size": 1.5  # 更大的标记
                })
                marker_id += 1

        return markers


class AdvancedWavePeaksValleysStrategy:
    """高级波峰波谷检测策略 - 基于开源算法"""

    def __init__(self):
        if not HAS_DATA_LOADER:
            raise ImportError("缺少 data_loader 模块")

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional[Any]:
        """
        扫描当前股票的高级波峰波谷

        Args:
            db_path: 数据库路径
            table_name: 表名

        Returns:
            显示结果，包含高级波峰波谷标记
        """
        # 加载股票数据
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"无法加载股票 {table_name} 的数据")

        candles, volumes, instrument = data

        # 执行高级波峰波谷检测
        markers = self.analyze_advanced_wave_peaks_valleys(candles)

        if not markers:
            return None

        # 统计信息
        peak_count = sum(1 for m in markers if "高级波峰" in m["text"])
        valley_count = sum(1 for m in markers if "高级波谷" in m["text"])

        status_message = f"高级算法检测到 {peak_count} 个波峰，{valley_count} 个波谷"

        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name="advanced_wave_peaks_valleys",
                markers=markers,
                status_message=status_message
            )
        else:
            # 如果没有DisplayResult类，返回简单的字典
            return {
                "strategy_name": "advanced_wave_peaks_valleys",
                "markers": markers,
                "status_message": status_message
            }

    def analyze_advanced_wave_peaks_valleys(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        使用高级算法分析股票的波峰波谷

        Args:
            candles: K线数据

        Returns:
            高级波峰波谷标记列表
        """
        if not candles or len(candles) < 50:
            return []

        # 创建高级波浪分析器
        analyzer = AdvancedWaveAnalyzer(candles)

        # 寻找波峰和波谷
        peaks, valleys = analyzer.find_significant_peaks_and_valleys(candles)

        # 生成标记
        markers = analyzer.generate_wave_markers(peaks, valleys, candles)

        return markers