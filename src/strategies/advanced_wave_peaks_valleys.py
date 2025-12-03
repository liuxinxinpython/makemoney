# strategies/advanced_wave_peaks_valleys.py

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


class AdvancedWaveAnalyzer:
    """高级波峰波谷检测器 - 基于Fractal算法"""

    def __init__(self, candles: List[Dict[str, Any]]):
        self.candles = candles

    def find_significant_peaks_and_valleys(self, candles: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
        """
        使用Fractal算法检测波峰和波谷 - 分析所有历史数据，标记明显波峰波谷
        Fractal: 当一根K线的high/low是前后各2根K线中的最高/最低时，标记为fractal
        """
        try:
            if len(candles) < 5:
                return [], []

            peaks = []
            valleys = []

            # Fractal检测：需要前后各2根K线，共5根K线
            for i in range(2, len(candles) - 2):
                # 检查是否为波峰：当前high是5根K线中的最高
                is_peak = True
                current_high = candles[i]['high']
                for j in range(i-2, i+3):
                    if j != i and candles[j]['high'] >= current_high:
                        is_peak = False
                        break
                if is_peak:
                    # 额外检查：波峰幅度要足够明显（相对于局部最低价的涨幅 > 0.5%）
                    local_lows = [candles[j]['low'] for j in range(i-2, i+3)]
                    min_local_low = min(local_lows)
                    amplitude_ratio = (current_high - min_local_low) / min_local_low
                    if amplitude_ratio > 0.005:  # 至少0.5%的幅度
                        peaks.append(i)

                # 检查是否为波谷：当前low是5根K线中的最低
                is_valley = True
                current_low = candles[i]['low']
                for j in range(i-2, i+3):
                    if j != i and candles[j]['low'] <= current_low:
                        is_valley = False
                        break
                if is_valley:
                    # 额外检查：波谷幅度要足够明显（相对于局部最高价的跌幅 > 0.5%）
                    local_highs = [candles[j]['high'] for j in range(i-2, i+3)]
                    max_local_high = max(local_highs)
                    amplitude_ratio = (max_local_high - current_low) / max_local_high
                    if amplitude_ratio > 0.005:  # 至少0.5%的幅度
                        valleys.append(i)

            # 优化1: 增加最小距离过滤，避免标记过于密集 (保持2根K线最小距离)
            peaks = self._filter_close_points(peaks, 2)
            valleys = self._filter_close_points(valleys, 2)

            # 优化1.5: 确保波峰波谷交替出现，避免连续同向标记
            peaks, valleys = self._ensure_alternating_peaks_valleys(peaks, valleys, candles)

            # 优化2: 限制总标记数量，避免性能问题
            max_markers = 400  # 限制在400个以内
            total_markers = len(peaks) + len(valleys)

            if total_markers > max_markers:
                # 如果标记太多，按重要性排序并保留最重要的
                peaks = self._prioritize_fractals_by_importance(peaks, candles, 'peak', max_markers // 2)
                valleys = self._prioritize_fractals_by_importance(valleys, candles, 'valley', max_markers // 2)

            print(f"Fractal detection: found {len(peaks)} peaks and {len(valleys)} valleys from {len(candles)} candles")

            return peaks, valleys
        except Exception as e:
            print(f"Error in find_significant_peaks_and_valleys: {e}")
            import traceback
            traceback.print_exc()
            return [], []

    def _prioritize_fractals_by_importance(self, fractals: List[int], candles: List[Dict[str, Any]],
                                          fractal_type: str, max_count: int) -> List[int]:
        """根据重要性对fractals进行排序并限制数量"""
        if len(fractals) <= max_count:
            return fractals

        # 计算每个fractal的重要性分数
        fractal_scores = []
        for idx in fractals:
            if fractal_type == 'peak':
                # 波峰重要性：基于价格偏离度和成交量
                if idx > 0 and idx < len(candles) - 1:
                    # 价格重要性：相对于局部均线的偏离程度
                    local_prices = [c['close'] for c in candles[max(0, idx-10):min(len(candles), idx+11)]]
                    local_mean = sum(local_prices) / len(local_prices)
                    price_deviation = abs(candles[idx]['high'] - local_mean) / local_mean

                    # 时间重要性：越新的fractal越重要
                    time_weight = idx / len(candles)

                    # 成交量重要性（如果有的话）
                    volume_weight = 1.0
                    if 'volume' in candles[idx] and candles[idx]['volume'] > 0:
                        # 计算局部平均成交量
                        local_volumes = [c.get('volume', 0) for c in candles[max(0, idx-5):min(len(candles), idx+6)]]
                        avg_volume = sum(local_volumes) / len(local_volumes) if local_volumes else 1
                        volume_weight = min(candles[idx]['volume'] / avg_volume, 2.0) if avg_volume > 0 else 1.0

                    score = price_deviation * (0.5 + 0.5 * time_weight) * volume_weight
                    fractal_scores.append((idx, score))

            elif fractal_type == 'valley':
                # 波谷重要性：基于价格偏离度和成交量
                if idx > 0 and idx < len(candles) - 1:
                    local_prices = [c['close'] for c in candles[max(0, idx-10):min(len(candles), idx+11)]]
                    local_mean = sum(local_prices) / len(local_prices)
                    price_deviation = abs(candles[idx]['low'] - local_mean) / local_mean

                    time_weight = idx / len(candles)

                    volume_weight = 1.0
                    if 'volume' in candles[idx] and candles[idx]['volume'] > 0:
                        local_volumes = [c.get('volume', 0) for c in candles[max(0, idx-5):min(len(candles), idx+6)]]
                        avg_volume = sum(local_volumes) / len(local_volumes) if local_volumes else 1
                        volume_weight = min(candles[idx]['volume'] / avg_volume, 2.0) if avg_volume > 0 else 1.0

                    score = price_deviation * (0.5 + 0.5 * time_weight) * volume_weight
                    fractal_scores.append((idx, score))

        # 按重要性分数降序排序
        fractal_scores.sort(key=lambda x: x[1], reverse=True)

        # 返回最重要的max_count个fractals
        return [idx for idx, score in fractal_scores[:max_count]]

    def _filter_close_points(self, points: List[int], min_distance: int) -> List[int]:
        """过滤掉距离太近的点"""
        if not points:
            return points

        filtered = [points[0]]
        for point in points[1:]:
            if point - filtered[-1] >= min_distance:
                filtered.append(point)

        return filtered

    def _ensure_alternating_peaks_valleys(self, peaks: List[int], valleys: List[int], candles: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
        """确保波峰和波谷交替出现，避免连续同向标记"""
        # 合并所有标记点并按时间排序
        all_points = []
        for idx in peaks:
            all_points.append(('peak', idx))
        for idx in valleys:
            all_points.append(('valley', idx))

        # 按索引排序
        all_points.sort(key=lambda x: x[1])

        # 过滤连续同向标记
        filtered_points = []
        prev_type = None

        for point_type, idx in all_points:
            if prev_type is None or point_type != prev_type:
                filtered_points.append((point_type, idx))
                prev_type = point_type
            # 如果是连续同向，跳过（保留第一个）

        # 分离回peaks和valleys
        new_peaks = [idx for pt, idx in filtered_points if pt == 'peak']
        new_valleys = [idx for pt, idx in filtered_points if pt == 'valley']

        return new_peaks, new_valleys

    def generate_wave_markers(self, peaks: List[int], valleys: List[int],
                            candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成波峰波谷标记 - 高级版本：Fractal算法"""
        # 限制显示最近的400个标记，按时间降序排序
        markers: List[Dict[str, Any]] = []
        marker_id = 0

        # 添加波峰标记 - 使用红色，标记真正的价格极值
        for idx in peaks:
            if 0 <= idx < len(candles):
                c = candles[idx]
                markers.append({
                    'id': f'peak_{marker_id}',
                    'time': c['time'],
                    'position': 'aboveBar',  # 波峰在上方显示
                    'color': '#ff4444',
                    'shape': 'arrowUp',
                    'text': f'波峰 {c["high"]:.2f}',
                })
                marker_id += 1

        # 添加波谷标记 - 使用绿色，标记真正的价格极值
        for idx in valleys:
            if 0 <= idx < len(candles):
                c = candles[idx]
                markers.append({
                    'id': f'valley_{marker_id}',
                    'time': c['time'],
                    'position': 'aboveBar',  # 改为aboveBar，与普通版一致
                    'color': '#44ff44',
                    'shape': 'arrowDown',
                    'text': f'波谷 {c["low"]:.2f}',
                })
                marker_id += 1

        # 按时间降序排序（最新的在前），限制为400个
        if len(markers) > 400:
            markers = sorted(markers, key=lambda m: m['time'], reverse=True)[:400]

        return markers


class AdvancedWavePeaksValleysStrategy:
    """高级波峰波谷检测策略 - 基于Fractal算法"""

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
            包含标记和状态信息的字典
        """
        # 加载股票数据
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"无法加载股票 {table_name} 的数据")

        candles, volumes, instrument = data

        # 执行高级波峰波谷检测
        analyzer = AdvancedWaveAnalyzer(candles)
        peaks, valleys = analyzer.find_significant_peaks_and_valleys(candles)

        # 生成标记
        markers = analyzer.generate_wave_markers(peaks, valleys, candles)

        # 统计信息
        peak_count = sum(1 for m in markers if "波峰" in m["text"])
        valley_count = sum(1 for m in markers if "波谷" in m["text"])

        status_message = f"高级Fractal算法检测到 {peak_count} 个波峰，{valley_count} 个波谷"

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
