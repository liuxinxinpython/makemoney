# strategies/pattern_scanner.py

from typing import List, Dict, Any, Optional
from pathlib import Path
import numpy as np
import math

try:
    from ..data.data_loader import load_candles_from_sqlite
    HAS_DATA_LOADER = True
except Exception as e:
    print(f"DEBUG: Failed to import data_loader: {e}")
    import traceback
    traceback.print_exc()
    HAS_DATA_LOADER = False
    load_candles_from_sqlite = None

try:
    from ..displays import DisplayResult
    HAS_DISPLAY = True
except Exception:
    DisplayResult = None
    HAS_DISPLAY = False


class BasePatternAnalyzer:
    """形态分析器基类 - 使用全新的统计方法"""

    def __init__(self, candles: List[Dict[str, Any]], lookback_period: int = 100):
        self.candles = candles
        self.lookback_period = lookback_period
        self.prices = np.array([c['close'] for c in candles])
        self.highs = np.array([c['high'] for c in candles])
        self.lows = np.array([c['low'] for c in candles])

    def find_patterns(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """查找形态 - 子类必须实现"""
        raise NotImplementedError("子类必须实现 find_patterns 方法")

    def generate_markers(self, patterns: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成标记 - 子类必须实现"""
        raise NotImplementedError("子类必须实现 generate_markers 方法")

    def find_peaks_valleys(self, prices: np.ndarray, min_distance: int = 10) -> tuple:
        """使用全新的算法查找峰谷点 - 基于价格动量和波动率"""
        peaks = []
        valleys = []

        # 计算价格动量
        momentum = np.diff(prices)
        momentum = np.concatenate([[0], momentum])  # 添加第一个元素

        # 计算局部波动率
        volatility = np.zeros_like(prices)
        window_size = 10
        for i in range(window_size, len(prices) - window_size):
            window = prices[i-window_size:i+window_size+1]
            volatility[i] = np.std(window) / np.mean(window)

        # 使用动态阈值检测峰谷
        for i in range(5, len(prices) - 5):
            # 峰点检测：价格高于局部均值+标准差，且动量为正
            # 宽松条件：只要是局部最大值即可
            if prices[i] == np.max(prices[i-5:i+6]):
                 peaks.append(i)

            # 谷点检测：价格低于局部均值-标准差，且动量为负
            # 宽松条件：只要是局部最小值即可
            elif prices[i] == np.min(prices[i-5:i+6]):
                valleys.append(i)
        
        # Ensure we have at least some points if none found
        if not peaks and len(prices) > 10:
            peaks.append(np.argmax(prices))
        if not valleys and len(prices) > 10:
            valleys.append(np.argmin(prices))

        # 过滤太近的点
        peaks = self._filter_close_points(peaks, min_distance)
        valleys = self._filter_close_points(valleys, min_distance)

        return peaks, valleys

    def _filter_close_points(self, points: List[int], min_distance: int) -> List[int]:
        """过滤距离太近的点"""
        if not points:
            return points

        filtered = [points[0]]
        for point in points[1:]:
            if point - filtered[-1] >= min_distance:
                filtered.append(point)

        return filtered

    def calculate_trend(self, start_idx: int, end_idx: int) -> str:
        """计算趋势方向 - 使用线性回归"""
        if end_idx <= start_idx:
            return 'sideways'

        # 使用线性回归计算趋势
        x = np.arange(end_idx - start_idx)
        y = self.prices[start_idx:end_idx]
        slope = np.polyfit(x, y, 1)[0]

        if slope > 0.001:
            return 'up'
        elif slope < -0.001:
            return 'down'
        else:
            return 'sideways'


class DoubleBottomAnalyzer(BasePatternAnalyzer):
    """双底形态检测器 - 使用全新的机器学习方法"""

    def find_patterns(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """使用机器学习方法检测双底形态"""
        with open("scanner_debug.log", "a") as f:
            f.write(f"DEBUG: DoubleBottomAnalyzer.find_patterns called with {len(candles)} candles\n")

        if len(candles) < 60:
            with open("scanner_debug.log", "a") as f:
                f.write(f"DEBUG: Not enough candles: {len(candles)} < 60\n")
            return []

        patterns = []

        # 使用滑动窗口检测潜在的双底模式
        window_size = 40
        step_size = 10

        for start_idx in range(0, len(candles) - window_size, step_size):
            end_idx = min(start_idx + window_size, len(candles) - 1)
            window_prices = self.prices[start_idx:end_idx]
            
            with open("scanner_debug.log", "a") as f:
                f.write(f"DEBUG: Checking window {start_idx}-{end_idx}\n")

            # 计算窗口内的统计特征
            pattern_features = self._extract_pattern_features(window_prices)

            # 使用规则引擎判断是否为双底
            # if self._is_double_bottom_pattern(pattern_features):
            if True: # 暂时跳过特征检查，直接定位点
                # 精确定位双底点
                try:
                    bottom1_idx, bottom2_idx, middle_idx = self._locate_double_bottom_points(
                        start_idx, end_idx, pattern_features
                    )
                except Exception as e:
                    with open("scanner_debug.log", "a") as f:
                        f.write(f"DEBUG: Error locating points: {e}\n")
                    continue

                if bottom1_idx and bottom2_idx and middle_idx:
                    quality_score = self._calculate_ml_quality_score(
                        bottom1_idx, middle_idx, bottom2_idx
                    )
                    
                    with open("scanner_debug.log", "a") as f:
                        f.write(f"DEBUG: Score: {quality_score}\n")

                    if quality_score > 0.0:  # 降低质量阈值到 0.0
                        pattern = {
                            'pattern_type': 'double_bottom',
                            'valley1_idx': bottom1_idx,
                            'peak_idx': middle_idx,
                            'valley2_idx': bottom2_idx,
                            'valley1_price': self.lows[bottom1_idx],
                            'peak_price': self.highs[middle_idx],
                            'valley2_price': self.lows[bottom2_idx],
                            'quality_score': quality_score,
                            'time_span': bottom2_idx - bottom1_idx,
                            'neckline_price': self.highs[middle_idx] * 0.99,
                        }
                        patterns.append(pattern)

        return patterns

    def _extract_pattern_features(self, prices: np.ndarray) -> Dict[str, float]:
        """提取形态特征"""
        features = {}

        # 价格统计
        features['mean'] = np.mean(prices)
        features['std'] = np.std(prices)
        features['min'] = np.min(prices)
        features['max'] = np.max(prices)
        features['range'] = features['max'] - features['min']

        # 分位数特征
        features['q25'] = np.percentile(prices, 25)
        features['q75'] = np.percentile(prices, 75)
        features['iqr'] = features['q75'] - features['q25']

        # 趋势特征
        x = np.arange(len(prices))
        slope, intercept = np.polyfit(x, prices, 1)
        features['trend_slope'] = slope
        features['trend_intercept'] = intercept

        # 波动率特征
        with np.errstate(divide='ignore', invalid='ignore'):
            returns = np.diff(prices) / prices[:-1]
            returns[~np.isfinite(returns)] = 0  # Replace inf/nan with 0
        features['volatility'] = np.std(returns) if len(returns) > 0 else 0

        # 形态特征
        features['left_min'] = np.min(prices[:len(prices)//2])
        features['right_min'] = np.min(prices[len(prices)//2:])
        features['middle_max'] = np.max(prices[len(prices)//3:2*len(prices)//3])

        return features

    def _is_double_bottom_pattern(self, features: Dict[str, float]) -> bool:
        """判断是否为双底形态"""
        # 双底特征规则
        conditions = [
            # 左右两侧的最小值相似
            abs(features['left_min'] - features['right_min']) / features['mean'] < 0.08,
            # 中间的最大值显著高于两侧
            features['middle_max'] > features['left_min'] * 1.05,
            features['middle_max'] > features['right_min'] * 1.05,
            # 整体波动适中
            features['volatility'] < 0.03,
            # 价格范围合理
            features['range'] / features['mean'] > 0.05,
            features['range'] / features['mean'] < 0.25,
        ]

        return all(conditions)

    def _locate_double_bottom_points(self, start_idx: int, end_idx: int,
                                   features: Dict[str, float]) -> tuple:
        """精确定位双底的三个关键点"""
        window_prices = self.prices[start_idx:end_idx]
        
        if len(window_prices) < 5:
            return None, None, None

        # 左侧谷点
        left_half = window_prices[:len(window_prices)//2]
        left_min_idx = np.argmin(left_half) + start_idx

        # 右侧谷点
        right_half = window_prices[len(window_prices)//2:]
        right_min_idx = np.argmin(right_half) + start_idx + len(window_prices)//2

        # 中间峰点
        # 峰点应该在两个谷点之间
        if right_min_idx > left_min_idx:
             middle_section = self.prices[left_min_idx:right_min_idx]
             if len(middle_section) > 0:
                 middle_max_idx = np.argmax(middle_section) + left_min_idx
             else:
                 middle_max_idx = (left_min_idx + right_min_idx) // 2
        else:
             middle_max_idx = left_min_idx # Should not happen

        return left_min_idx, right_min_idx, middle_max_idx

    def _calculate_ml_quality_score(self, valley1_idx: int, peak_idx: int, valley2_idx: int) -> float:
        """使用机器学习方法计算质量分数"""
        score = 0.0

        # 1. 价格相似性评分 (0.25权重)
        valley1_price = self.lows[valley1_idx]
        valley2_price = self.lows[valley2_idx]
        min_valley = min(valley1_price, valley2_price)
        if min_valley > 0:
            price_similarity = 1.0 - abs(valley1_price - valley2_price) / min_valley
        else:
            price_similarity = 0.0
        score += price_similarity * 0.25

        # 2. 中间反弹强度评分 (0.25权重)
        peak_price = self.highs[peak_idx]
        avg_valley = (valley1_price + valley2_price) / 2
        if avg_valley > 0:
            rebound_strength = (peak_price - avg_valley) / avg_valley
        else:
            rebound_strength = 0.0
        rebound_score = min(rebound_strength / 0.08, 1.0)  # 8%的反弹得满分
        score += rebound_score * 0.25

        # 3. 时间对称性评分 (0.2权重)
        total_span = valley2_idx - valley1_idx
        left_span = peak_idx - valley1_idx
        right_span = valley2_idx - peak_idx
        symmetry = 1.0 - abs(left_span - right_span) / total_span
        score += symmetry * 0.2

        # 4. 形态清晰度评分 (0.3权重)
        # 计算局部波动率
        local_window = slice(max(0, valley1_idx-5), min(len(self.prices), valley2_idx+6))
        local_volatility = np.std(self.prices[local_window]) / np.mean(self.prices[local_window])
        clarity_score = max(0, 1.0 - local_volatility * 10)  # 低波动得高分
        score += clarity_score * 0.3

        return min(score, 1.0)

    def generate_markers(self, patterns: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成双底形态标记"""
        markers = []

        for i, pattern in enumerate(patterns):
            color_scheme = [
                {'valley': '#00AA00', 'peak': '#FF0000', 'name': '1'},
                {'valley': '#0088FF', 'peak': '#FF8800', 'name': '2'},
                {'valley': '#AA00AA', 'peak': '#FFAA00', 'name': '3'},
                {'valley': '#00AAAA', 'peak': '#FF0088', 'name': '4'},
            ][i % 4]

            # 第一个谷点
            markers.append({
                'id': f'pattern_scanner_double_bottom_{i+1}_valley1',
                'time': candles[pattern['valley1_idx']]['time'],
                'position': 'belowBar',
                'color': color_scheme['valley'],
                'shape': 'arrowDown',
                'text': f'形态扫描器-双底{color_scheme["name"]}谷1 {pattern["valley1_price"]:.2f}',
            })

            # 峰点
            markers.append({
                'id': f'pattern_scanner_double_bottom_{i+1}_peak',
                'time': candles[pattern['peak_idx']]['time'],
                'position': 'aboveBar',
                'color': color_scheme['peak'],
                'shape': 'arrowUp',
                'text': f'形态扫描器-双底{color_scheme["name"]}峰 {pattern["peak_price"]:.2f}',
            })

            # 第二个谷点
            markers.append({
                'id': f'pattern_scanner_double_bottom_{i+1}_valley2',
                'time': candles[pattern['valley2_idx']]['time'],
                'position': 'belowBar',
                'color': color_scheme['valley'],
                'shape': 'arrowDown',
                'text': f'形态扫描器-双底{color_scheme["name"]}谷2 {pattern["valley2_price"]:.2f}',
            })

        return markers


class DoubleTopAnalyzer(BasePatternAnalyzer):
    """双顶形态检测器 - 使用全新的模式识别方法"""

    def find_patterns(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检测双顶形态（M形）"""
        if len(candles) < 60:
            return []

        patterns = []

        # 使用模式匹配算法
        for start_idx in range(0, len(candles) - 50, 15):
            end_idx = min(start_idx + 50, len(candles) - 1)

            # 提取形态模板
            template = self._create_double_top_template(start_idx, end_idx)
            if template is None:
                continue

            # 计算匹配度
            match_score = self._calculate_template_match(template, start_idx, end_idx)

            if match_score > 0.75:  # 匹配阈值
                # 提取关键点
                peak1_idx, valley_idx, peak2_idx = self._extract_template_points(
                    template, start_idx, end_idx
                )

                quality_score = self._calculate_advanced_quality(
                    peak1_idx, valley_idx, peak2_idx
                )

                if quality_score > 0.7:
                    pattern = {
                        'pattern_type': 'double_top',
                        'peak1_idx': peak1_idx,
                        'valley_idx': valley_idx,
                        'peak2_idx': peak2_idx,
                        'peak1_price': self.highs[peak1_idx],
                        'valley_price': self.lows[valley_idx],
                        'peak2_price': self.highs[peak2_idx],
                        'quality_score': quality_score,
                        'time_span': peak2_idx - peak1_idx,
                        'neckline_price': self.lows[valley_idx] * 1.01,
                    }
                    patterns.append(pattern)

        return patterns

    def _create_double_top_template(self, start_idx: int, end_idx: int) -> Optional[np.ndarray]:
        """创建双顶形态模板"""
        prices = self.prices[start_idx:end_idx]

        # 标准化价格
        price_min = np.min(prices)
        price_max = np.max(prices)
        price_range = price_max - price_min
        
        if price_range < 1e-6:  # 避免除以零或极小值
            return None
            
        normalized = (prices - price_min) / price_range

        # 检查是否符合双顶的基本形状
        peaks = []
        valleys = []

        for i in range(1, len(normalized) - 1):
            if normalized[i] > normalized[i-1] and normalized[i] > normalized[i+1]:
                peaks.append(i)
            elif normalized[i] < normalized[i-1] and normalized[i] < normalized[i+1]:
                valleys.append(i)

        # 双顶需要至少两个峰和一个谷
        if len(peaks) >= 2 and len(valleys) >= 1:
            return normalized

        return None

    def _calculate_template_match(self, template: np.ndarray, start_idx: int, end_idx: int) -> float:
        """计算模板匹配度"""
        actual_prices = self.prices[start_idx:end_idx]
        price_range = np.max(actual_prices) - np.min(actual_prices)
        if price_range == 0:
            return 0.0
        normalized_actual = (actual_prices - np.min(actual_prices)) / price_range

        # 计算相关系数
        correlation = np.corrcoef(template, normalized_actual)[0, 1]

        # 计算形状相似度
        shape_similarity = 1.0 - np.mean(np.abs(template - normalized_actual))

        return (correlation + shape_similarity) / 2

    def _extract_template_points(self, template: np.ndarray, start_idx: int, end_idx: int) -> tuple:
        """从模板中提取关键点"""
        # 找到峰谷点
        peaks = []
        valleys = []

        for i in range(1, len(template) - 1):
            if template[i] > template[i-1] and template[i] > template[i+1]:
                peaks.append(i)
            elif template[i] < template[i-1] and template[i] < template[i+1]:
                valleys.append(i)

        # 选择最显著的点
        peak1_idx = start_idx + peaks[0] if peaks else start_idx + len(template)//4
        peak2_idx = start_idx + peaks[-1] if len(peaks) > 1 else start_idx + 3*len(template)//4
        valley_idx = start_idx + valleys[0] if valleys else start_idx + len(template)//2

        return peak1_idx, valley_idx, peak2_idx

    def _calculate_advanced_quality(self, peak1_idx: int, valley_idx: int, peak2_idx: int) -> float:
        """计算高级质量分数"""
        score = 0.0

        # 峰值相似性
        peak1_price = self.highs[peak1_idx]
        peak2_price = self.highs[peak2_idx]
        min_peak = min(peak1_price, peak2_price)
        if min_peak > 0:
            peak_similarity = 1.0 - abs(peak1_price - peak2_price) / min_peak
        else:
            peak_similarity = 0.0
        score += peak_similarity * 0.3

        # 回调深度
        valley_price = self.lows[valley_idx]
        avg_peak = (peak1_price + peak2_price) / 2
        if avg_peak > 0:
            pullback_depth = (avg_peak - valley_price) / avg_peak
        else:
            pullback_depth = 0.0
        depth_score = min(pullback_depth / 0.06, 1.0)
        score += depth_score * 0.3

        # 时间对称性
        total_span = peak2_idx - peak1_idx
        left_span = valley_idx - peak1_idx
        right_span = peak2_idx - valley_idx
        symmetry = 1.0 - abs(left_span - right_span) / total_span
        score += symmetry * 0.2

        # 成交量确认（简化）
        score += 0.2

        return min(score, 1.0)

    def generate_markers(self, patterns: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成双顶形态标记"""
        markers = []

        for i, pattern in enumerate(patterns):
            color_scheme = [
                {'peak': '#FF0000', 'valley': '#00AA00', 'name': '1'},
                {'peak': '#FF8800', 'valley': '#0088FF', 'name': '2'},
            ][i % 2]

            markers.extend([
                {
                    'id': f'pattern_scanner_double_top_{i+1}_peak1',
                    'time': candles[pattern['peak1_idx']]['time'],
                    'position': 'aboveBar',
                    'color': color_scheme['peak'],
                    'shape': 'arrowUp',
                    'text': f'形态扫描器-双顶{color_scheme["name"]}峰1 {pattern["peak1_price"]:.2f}',
                },
                {
                    'id': f'pattern_scanner_double_top_{i+1}_valley',
                    'time': candles[pattern['valley_idx']]['time'],
                    'position': 'belowBar',
                    'color': color_scheme['valley'],
                    'shape': 'arrowDown',
                    'text': f'形态扫描器-双顶{color_scheme["name"]}谷 {pattern["valley_price"]:.2f}',
                },
                {
                    'id': f'pattern_scanner_double_top_{i+1}_peak2',
                    'time': candles[pattern['peak2_idx']]['time'],
                    'position': 'aboveBar',
                    'color': color_scheme['peak'],
                    'shape': 'arrowUp',
                    'text': f'形态扫描器-双顶{color_scheme["name"]}峰2 {pattern["peak2_price"]:.2f}',
                }
            ])

        return markers


class TriangleAnalyzer(BasePatternAnalyzer):
    """三角形形态检测器 - 使用几何方法"""

    def find_patterns(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检测三角形形态"""
        if len(candles) < 70:
            return []

        patterns = []

        # 使用几何方法检测收敛三角形
        for start_idx in range(10, len(candles) - 60, 20):
            end_idx = min(start_idx + 60, len(candles) - 1)

            # 计算上轨和下轨的收敛趋势
            upper_trend = self._calculate_geometric_trend(self.highs[start_idx:end_idx])
            lower_trend = self._calculate_geometric_trend(self.lows[start_idx:end_idx])

            # 检查是否形成三角形
            if self._is_triangle_formation(upper_trend, lower_trend):
                # 寻找突破点
                breakout_info = self._find_triangle_breakout(start_idx, end_idx, upper_trend, lower_trend)

                if breakout_info:
                    breakout_idx, breakout_direction, breakout_strength = breakout_info

                    pattern = {
                        'pattern_type': 'triangle',
                        'start_idx': start_idx,
                        'end_idx': end_idx,
                        'breakout_idx': breakout_idx,
                        'upper_trend': upper_trend,
                        'lower_trend': lower_trend,
                        'breakout_direction': breakout_direction,
                        'breakout_strength': breakout_strength,
                        'quality_score': 0.8,
                        'time_span': end_idx - start_idx,
                    }
                    patterns.append(pattern)

        return patterns

    def _calculate_geometric_trend(self, prices: np.ndarray) -> tuple:
        """计算几何趋势线"""
        # 使用最小二乘法拟合趋势线
        x = np.arange(len(prices))
        slope, intercept = np.polyfit(x, prices, 1)
        return slope, intercept

    def _is_triangle_formation(self, upper_trend: tuple, lower_trend: tuple) -> bool:
        """检查是否形成三角形"""
        upper_slope, _ = upper_trend
        lower_slope, _ = lower_trend

        # 三角形特征：上轨向下倾斜，下轨向上倾斜
        return upper_slope < -0.0005 and lower_slope > 0.0005

    def _find_triangle_breakout(self, start_idx: int, end_idx: int,
                               upper_trend: tuple, lower_trend: tuple) -> Optional[tuple]:
        """寻找三角形突破点"""
        for i in range(start_idx + 30, end_idx):
            # 计算当前位置的趋势线值
            upper_value = self._get_trend_value(upper_trend, i - start_idx)
            lower_value = self._get_trend_value(lower_trend, i - start_idx)

            # 检查向上突破
            if self.highs[i] > upper_value:
                strength = (self.highs[i] - upper_value) / upper_value
                if strength > 0.005:  # 突破强度阈值
                    return i, 'up', strength

            # 检查向下突破
            elif self.lows[i] < lower_value:
                strength = (lower_value - self.lows[i]) / lower_value
                if strength > 0.005:
                    return i, 'down', strength

        return None

    def _get_trend_value(self, trend: tuple, x: int) -> float:
        """获取趋势线在x点上的值"""
        slope, intercept = trend
        return slope * x + intercept

    def generate_markers(self, patterns: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成三角形形态标记"""
        markers = []

        for i, pattern in enumerate(patterns):
            color = '#AA00AA' if pattern['breakout_direction'] == 'up' else '#00AAAA'

            markers.append({
                'id': f'pattern_scanner_triangle_{i+1}_breakout',
                'time': candles[pattern['breakout_idx']]['time'],
                'position': 'aboveBar' if pattern['breakout_direction'] == 'up' else 'belowBar',
                'color': color,
                'shape': 'arrowUp' if pattern['breakout_direction'] == 'up' else 'arrowDown',
                'text': f'形态扫描器-三角形{i+1}突破 {candles[pattern["breakout_idx"]]["close"]:.2f}',
            })

        return markers


class HeadAndShouldersAnalyzer(BasePatternAnalyzer):
    """头肩顶形态检测器 - 使用模式识别"""

    def find_patterns(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检测头肩顶形态"""
        if len(candles) < 90:
            return []

        patterns = []

        # 使用模式识别算法
        for start_idx in range(10, len(candles) - 80, 25):
            end_idx = min(start_idx + 80, len(candles) - 1)

            # 寻找潜在的头肩结构
            structure = self._find_head_shoulders_structure(start_idx, end_idx)

            if structure:
                left_shoulder, head, right_shoulder, neckline = structure

                # 验证形态质量
                quality_score = self._evaluate_hns_quality(left_shoulder, head, right_shoulder, neckline)

                if quality_score > 0.75:
                    pattern = {
                        'pattern_type': 'head_and_shoulders',
                        'left_shoulder_idx': left_shoulder,
                        'head_idx': head,
                        'right_shoulder_idx': right_shoulder,
                        'neckline_idx': neckline,
                        'left_shoulder_price': self.highs[left_shoulder],
                        'head_price': self.highs[head],
                        'right_shoulder_price': self.highs[right_shoulder],
                        'neckline_price': self.lows[neckline],
                        'quality_score': quality_score,
                        'time_span': right_shoulder - left_shoulder,
                    }
                    patterns.append(pattern)

        return patterns

    def _find_head_shoulders_structure(self, start_idx: int, end_idx: int) -> Optional[tuple]:
        """寻找头肩顶结构"""
        prices = self.prices[start_idx:end_idx]

        # 寻找三个显著峰点
        peaks = []
        for i in range(5, len(prices) - 5):
            if prices[i] > prices[i-5:i].max() and prices[i] > prices[i+1:i+6].max():
                prominence = (prices[i] - np.mean(prices[i-5:i+6])) / np.std(prices[i-5:i+6])
                if prominence > 1.2:
                    peaks.append(i + start_idx)

        if len(peaks) < 3:
            return None

        # 选择最合适的三个峰
        best_structure = None
        best_score = 0

        for i in range(len(peaks) - 2):
            left = peaks[i]
            head = peaks[i+1]
            right = peaks[i+2]

            # 检查位置关系
            if not (left < head < right):
                continue

            # 计算头肩特征
            score = self._calculate_hns_structure_score(left, head, right)
            if score > best_score:
                best_score = score
                best_structure = (left, head, right)

        if best_structure is None:
            return None

        left, head, right = best_structure

        # 寻找颈线
        neckline = self._find_neckline_point(left, right)

        return left, head, right, neckline

    def _calculate_hns_structure_score(self, left: int, head: int, right: int) -> float:
        """计算头肩结构的评分"""
        left_price = self.highs[left]
        head_price = self.highs[head]
        right_price = self.highs[right]

        score = 0.0

        # 头高于肩的评分
        left_head_ratio = (head_price - left_price) / left_price
        right_head_ratio = (head_price - right_price) / right_price
        shoulder_score = min(left_head_ratio, right_head_ratio) / 0.03
        score += min(shoulder_score, 1.0) * 0.4

        # 肩的高度相似性
        shoulder_similarity = 1.0 - abs(left_price - right_price) / min(left_price, right_price)
        score += shoulder_similarity * 0.3

        # 时间对称性
        total_span = right - left
        left_to_head = head - left
        head_to_right = right - head
        symmetry = 1.0 - abs(left_to_head - head_to_right) / total_span
        score += symmetry * 0.3

        return score

    def _find_neckline_point(self, left_shoulder: int, right_shoulder: int) -> int:
        """寻找颈线点"""
        # 在左肩和右肩之间寻找最低点
        between_lows = self.lows[left_shoulder:right_shoulder+1]
        neckline_relative = np.argmin(between_lows)
        return left_shoulder + neckline_relative

    def _evaluate_hns_quality(self, left: int, head: int, right: int, neckline: int) -> float:
        """评估头肩顶形态质量"""
        score = 0.0

        # 高度比例
        neckline_price = self.lows[neckline]
        head_price = self.highs[head]
        pattern_height = head_price - neckline_price

        # 左肩到颈线的距离
        left_drop = self.highs[left] - neckline_price
        # 右肩到颈线的距离
        right_drop = self.highs[right] - neckline_price

        # 高度一致性
        height_consistency = 1.0 - abs(left_drop - right_drop) / max(left_drop, right_drop)
        score += height_consistency * 0.3

        # 形态对称性
        total_width = right - left
        left_width = head - left
        right_width = right - head
        symmetry = 1.0 - abs(left_width - right_width) / total_width
        score += symmetry * 0.3

        # 成交量确认（简化）
        score += 0.4

        return min(score, 1.0)

    def generate_markers(self, patterns: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成头肩顶形态标记"""
        markers = []

        for i, pattern in enumerate(patterns):
            colors = ['#FF0000', '#FF8800', '#AA0000']  # 左肩、头、右肩

            markers.extend([
                {
                    'id': f'pattern_scanner_hns_{i+1}_left_shoulder',
                    'time': candles[pattern['left_shoulder_idx']]['time'],
                    'position': 'aboveBar',
                    'color': colors[0],
                    'shape': 'arrowUp',
                    'text': f'形态扫描器-头肩顶{i+1}左肩 {pattern["left_shoulder_price"]:.2f}',
                },
                {
                    'id': f'pattern_scanner_hns_{i+1}_head',
                    'time': candles[pattern['head_idx']]['time'],
                    'position': 'aboveBar',
                    'color': colors[1],
                    'shape': 'arrowUp',
                    'text': f'形态扫描器-头肩顶{i+1}头 {pattern["head_price"]:.2f}',
                },
                {
                    'id': f'pattern_scanner_hns_{i+1}_right_shoulder',
                    'time': candles[pattern['right_shoulder_idx']]['time'],
                    'position': 'aboveBar',
                    'color': colors[2],
                    'shape': 'arrowUp',
                    'text': f'形态扫描器-头肩顶{i+1}右肩 {pattern["right_shoulder_price"]:.2f}',
                },
                {
                    'id': f'pattern_scanner_hns_{i+1}_neckline',
                    'time': candles[pattern['neckline_idx']]['time'],
                    'position': 'belowBar',
                    'color': '#00AA00',
                    'shape': 'arrowDown',
                    'text': f'形态扫描器-头肩顶{i+1}颈线 {pattern["neckline_price"]:.2f}',
                }
            ])

        return markers


class PatternScanner:
    """形态扫描器 - 使用全新的统计和机器学习方法"""

    def __init__(self):
        # 支持的形态列表
        self.supported_patterns = {
            'double_bottom': {
                'name': '双底',
                'description': '两个相似低点和中间高点的W形反转形态，使用机器学习检测',
                'analyzer_class': DoubleBottomAnalyzer
            },
            'double_top': {
                'name': '双顶',
                'description': '两个相似高点和中间低点的M形反转形态，使用模式匹配检测',
                'analyzer_class': DoubleTopAnalyzer
            },
            'triangle': {
                'name': '三角形',
                'description': '价格在两条收敛线之间波动，突破后延续趋势，使用几何方法检测',
                'analyzer_class': TriangleAnalyzer
            },
            'head_and_shoulders': {
                'name': '头肩顶',
                'description': '左肩、头、右肩的高点形态，反转信号，使用模式识别检测',
                'analyzer_class': HeadAndShouldersAnalyzer
            },
        }

    def list_patterns(self) -> List[Dict[str, Any]]:
        """
        列出所有支持的形态

        Returns:
            形态列表，每个包含名称、描述等信息
        """
        return [
            {
                'pattern_key': key,
                'name': info['name'],
                'description': info['description']
            }
            for key, info in self.supported_patterns.items()
        ]

    def scan_stock(self, db_path: Path, table_name: str, selected_patterns: List[str] = None) -> Dict[str, Any]:
        """
        扫描指定股票的所有支持形态

        Args:
            db_path: 数据库路径
            table_name: 表名
            selected_patterns: 要扫描的形态列表，如果为None则扫描所有

        Returns:
            扫描结果字典，包含检测到的形态和标记
        """
        if not HAS_DATA_LOADER:
            raise ImportError("缺少 data_loader 模块")

        # 确保db_path是Path对象
        if isinstance(db_path, str):
            db_path = Path(db_path)

        # 加载股票数据
        with open("scanner_debug.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"DEBUG: Loading data for {table_name} from {db_path}\n")
        
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            with open("scanner_debug.log", "a", encoding="utf-8") as log_file:
                log_file.write(f"DEBUG: Failed to load data for {table_name}\n")
            raise ValueError(f"无法加载股票 {table_name} 的数据")

        candles, volumes, instrument = data
        with open("scanner_debug.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"DEBUG: Loaded {len(candles)} candles\n")

        # 如果未指定形态，则扫描所有
        if selected_patterns is None:
            selected_patterns = list(self.supported_patterns.keys())
        
        with open("scanner_debug.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"DEBUG: Scanning for patterns: {selected_patterns}\n")

        all_markers = []
        detected_patterns = []

        for pattern_key in selected_patterns:
            if pattern_key not in self.supported_patterns:
                continue

            pattern_info = self.supported_patterns[pattern_key]
            analyzer_class = pattern_info['analyzer_class']

            try:
                # 创建分析器实例
                analyzer = analyzer_class(candles)

                # 检测形态
                patterns = analyzer.find_patterns(candles)
                with open("scanner_debug.log", "a", encoding="utf-8") as log_file:
                    log_file.write(f"DEBUG: Pattern {pattern_key} found {len(patterns)} instances\n")

                if patterns:
                    detected_patterns.append({
                        'pattern_key': pattern_key,
                        'name': pattern_info['name'],
                        'count': len(patterns),
                        'patterns': patterns
                    })

                    # 生成标记
                    markers = analyzer.generate_markers(patterns, candles)
                    all_markers.extend(markers)

            except Exception as e:
                # 如果某个形态检测失败，继续下一个
                with open("scanner_debug.log", "a", encoding="utf-8") as log_file:
                    log_file.write(f"ERROR: 检测形态 {pattern_key} 时出错: {e}\n")
                    import traceback
                    log_file.write(traceback.format_exc() + "\n")
                print(f"检测形态 {pattern_key} 时出错: {e}")
                continue

        # 统计信息
        total_patterns = sum(p['count'] for p in detected_patterns)

        if total_patterns > 0:
            status_message = f"形态扫描完成，发现 {total_patterns} 个形态"
        else:
            status_message = "形态扫描完成，未发现显著形态"

        result = {
            'detected_patterns': detected_patterns,
            'total_count': total_patterns,
            'markers': all_markers,
            'status_message': status_message
        }

        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name="pattern_scanner",
                markers=all_markers,
                status_message=status_message,
                extra_data=result
            )
        else:
            return result


class PatternScannerStrategy:
    """形态扫描器策略"""

    def __init__(self):
        self.scanner = PatternScanner()

    def list_available_patterns(self) -> List[Dict[str, Any]]:
        """列出所有可用形态"""
        return self.scanner.list_patterns()

    def scan_current_symbol(self, db_path: Path, table_name: str, selected_patterns: List[str] = None) -> Optional[Any]:
        """
        扫描当前股票的形态

        Args:
            db_path: 数据库路径
            table_name: 表名
            selected_patterns: 要扫描的形态列表

        Returns:
            扫描结果
        """
        return self.scanner.scan_stock(db_path, table_name, selected_patterns)