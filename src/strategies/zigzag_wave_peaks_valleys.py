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

try:
    from ..research import StrategyContext, StrategyRunResult
    from ..research.models import StrategyParameter
except Exception:
    StrategyContext = None
    StrategyRunResult = None
    StrategyParameter = None

from .helpers import serialize_run_result


if StrategyParameter is not None:
    ZIGZAG_STRATEGY_PARAMETERS: List[StrategyParameter] = [
        StrategyParameter(
            key="min_reversal",
            label="最小反转(%)",
            type="number",
            default=5.0,
            description="忽略幅度低于该百分比的价格波动",
        ),
        StrategyParameter(
            key="retest_tolerance_pct",
            label="回踩容差(%)",
            type="number",
            default=1.2,
            description="第二个波谷相对基准波谷允许的最大价格偏差",
        ),
        StrategyParameter(
            key="uptrend_window",
            label="上涨确认窗口",
            type="number",
            default=5,
            description="回踩后统计斜率所使用的K线数量",
        ),
        StrategyParameter(
            key="min_uptrend_slope_pct",
            label="上涨斜率阈值(%)",
            type="number",
            default=0.15,
            description="确认买点所需的最小平均斜率 (按单根K线百分比计)",
        ),
        StrategyParameter(
            key="resistance_tolerance_pct",
            label="压力容差(%)",
            type="number",
            default=1.2,
            description="触及中枢波峰视为遇阻时允许的价格偏差",
        ),
        StrategyParameter(
            key="slowdown_window",
            label="放缓检测窗口",
            type="number",
            default=4,
            description="判断上行动能放缓所使用的K线数量",
        ),
        StrategyParameter(
            key="slowdown_slope_pct",
            label="放缓斜率上限(%)",
            type="number",
            default=0.04,
            description="放缓/走平判定允许的最大平均斜率 (按单根K线百分比计)",
        ),
        StrategyParameter(
            key="upper_shadow_ratio_pct",
            label="长上影比例(%)",
            type="number",
            default=55.0,
            description="长上影线触发卖点时上影长度占整根K线区间的比例",
        ),
        StrategyParameter(
            key="stop_loss_pct",
            label="回踩止损(%)",
            type="number",
            default=5.0,
            description="跌破基准/回踩波谷后触发止损的幅度",
        ),
        StrategyParameter(
            key="min_progress_pct",
            label="趋势确认涨幅(%)",
            type="number",
            default=3.0,
            description="认为涨势已经展开所需的最小涨幅 (用于走平卖点)",
        ),
    ]
else:  # pragma: no cover - optional UI metadata
    ZIGZAG_STRATEGY_PARAMETERS = []


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

    def generate_trade_markers(
        self,
        peaks: List[int],
        valleys: List[int],
        candles: List[Dict[str, Any]],
        *,
        retest_tolerance: float,
        uptrend_window: int,
        min_uptrend_slope: float,
        resistance_tolerance: float,
        slowdown_window: int,
        slowdown_slope: float,
        upper_shadow_ratio: float,
        stop_loss_pct: float,
        min_progress_pct: float,
    ) -> Tuple[List[Dict[str, Any]], int, int, Dict[str, int]]:
        """基于用户规则生成买卖点标记及退出统计"""

        trade_markers: List[Dict[str, Any]] = []
        context_markers: List[Dict[str, Any]] = []
        context_seen: set[str] = set()
        base_valley_seen: set[int] = set()
        buy_count = 0
        sell_count = 0
        exit_counter: Dict[str, int] = {
            "stop": 0,
            "resistance": 0,
            "upper_shadow": 0,
            "flatten": 0,
            "pending": 0,
        }

        pivot_sequence = self._build_pivots(peaks, valleys)
        for i in range(len(pivot_sequence) - 2):
            first_idx, first_type = pivot_sequence[i]
            second_idx, second_type = pivot_sequence[i + 1]
            third_idx, third_type = pivot_sequence[i + 2]

            if first_type != "valley" or second_type != "peak" or third_type != "valley":
                continue

            if first_idx >= len(candles) or second_idx >= len(candles) or third_idx >= len(candles):
                continue


            valley1_low = candles[first_idx]["low"]
            valley2_low = candles[third_idx]["low"]
            base_price = valley1_low if valley1_low != 0 else valley2_low
            if base_price == 0:
                continue

            if abs(valley2_low - valley1_low) / base_price > retest_tolerance:
                continue

            slope_idx = min(len(candles) - 1, third_idx + uptrend_window - 1)
            slope = self._calc_slope(candles, slope_idx, uptrend_window)
            if slope < min_uptrend_slope:
                continue

            exit_info = self._find_exit_point(
                candles,
                buy_idx=slope_idx,
                peak_idx=second_idx,
                valley_low=min(valley1_low, valley2_low),
                buy_price=candles[slope_idx]["close"],
                tolerance=resistance_tolerance,
                slowdown_window=slowdown_window,
                slowdown_slope=slowdown_slope,
                upper_shadow_ratio=upper_shadow_ratio,
                stop_loss_pct=stop_loss_pct,
                min_progress_pct=min_progress_pct,
            )

            if exit_info is not None:
                sell_idx, exit_reason = exit_info
            else:
                sell_idx = self._fallback_exit_index(candles, slope_idx)
                exit_reason = "pending"

            buy_count += 1
            buy_candle = candles[slope_idx]
            trade_markers.append({
                "id": f"zigzag_buy_signal_{slope_idx}",
                "time": buy_candle["time"],
                "position": "belowBar",
                "color": "#e03131",
                "shape": "arrowUp",
                "text": f"回踩谷买点 {buy_candle['close']:.2f}",
            })

            if first_idx not in base_valley_seen:
                base_valley_seen.add(first_idx)
                base_valley_candle = candles[first_idx]
                context_markers.append({
                    "id": f"zigzag_base_valley_{first_idx}",
                    "time": base_valley_candle["time"],
                    "position": "belowBar",
                    "color": "#61c454",
                    "shape": "circle",
                    "text": f"基准波谷 {base_valley_candle['low']:.2f}",
                })

            retest_valley_candle = candles[third_idx]
            context_markers.append({
                "id": f"zigzag_retest_valley_{third_idx}",
                "time": retest_valley_candle["time"],
                "position": "belowBar",
                "color": "#40c057",
                "shape": "circle",
                "text": f"回踩波谷 {retest_valley_candle['low']:.2f}",
            })

            peak_id = f"zigzag_mid_peak_{second_idx}"
            if peak_id not in context_seen:
                context_seen.add(peak_id)
                peak_candle = candles[second_idx]
                context_markers.append({
                    "id": peak_id,
                    "time": peak_candle["time"],
                    "position": "aboveBar",
                    "color": "#f2b705",
                    "shape": "circle",
                    "text": f"中继波峰 {peak_candle['high']:.2f}",
                })

            sell_candle = candles[sell_idx]
            sell_count += 1
            exit_counter[exit_reason] = exit_counter.get(exit_reason, 0) + 1
            if exit_reason == "stop":
                marker_color = "#2f9e44"
                marker_text = f"止损卖点 {sell_candle['close']:.2f}"
            elif exit_reason == "resistance":
                marker_color = "#2f9e44"
                marker_text = f"压力回落卖点 {sell_candle['close']:.2f}"
            elif exit_reason == "upper_shadow":
                marker_color = "#2f9e44"
                marker_text = f"长上影线卖点 {sell_candle['close']:.2f}"
            elif exit_reason == "flatten":
                marker_color = "#2f9e44"
                marker_text = f"趋势走平卖点 {sell_candle['close']:.2f}"
            else:
                marker_color = "#2f9e44"
                marker_text = f"待确认卖点 {sell_candle['close']:.2f}"

            trade_markers.append({
                "id": f"zigzag_sell_signal_{sell_idx}",
                "time": sell_candle["time"],
                "position": "aboveBar",
                "color": marker_color,
                "shape": "arrowDown",
                "text": marker_text,
            })

        trade_markers.extend(context_markers)
        return trade_markers, buy_count, sell_count, exit_counter

    def _build_pivots(self, peaks: List[int], valleys: List[int]) -> List[Tuple[int, str]]:
        """按时间顺序合并波峰与波谷索引"""
        pivots: List[Tuple[int, str]] = []
        for idx in peaks:
            pivots.append((idx, "peak"))
        for idx in valleys:
            pivots.append((idx, "valley"))
        pivots.sort(key=lambda item: item[0])
        return pivots

    def _find_exit_point(
        self,
        candles: List[Dict[str, Any]],
        *,
        buy_idx: int,
        peak_idx: int,
        valley_low: float,
        buy_price: float,
        tolerance: float,
        slowdown_window: int,
        slowdown_slope: float,
        upper_shadow_ratio: float,
        stop_loss_pct: float,
        min_progress_pct: float,
    ) -> Optional[Tuple[int, str]]:
        """查找与买点关联的退出信号"""
        if peak_idx >= len(candles) or buy_idx >= len(candles):
            return None

        reference_price = candles[peak_idx]["high"]
        if reference_price <= 0:
            return None

        stop_level = max(0.0, valley_low * (1 - stop_loss_pct))
        threshold_price = reference_price * (1 - tolerance)
        progress_threshold = buy_price * (1 + max(0.0, min_progress_pct))
        max_close = buy_price
        made_progress = False

        for idx in range(buy_idx + 1, len(candles)):
            candle = candles[idx]
            if candle["low"] <= stop_level:
                return idx, "stop"

            max_close = max(max_close, candle["close"])
            if not made_progress and max_close >= progress_threshold:
                made_progress = True

            if self._has_long_upper_shadow(candle, upper_shadow_ratio) and candle["close"] >= buy_price:
                return idx, "upper_shadow"

            if candle["high"] >= threshold_price:
                slope = self._calc_slope(candles, idx, slowdown_window)
                if slope <= slowdown_slope:
                    return idx, "resistance"

            if made_progress and (idx - buy_idx) >= slowdown_window:
                slope = self._calc_slope(candles, idx, slowdown_window)
                if slope <= slowdown_slope:
                    return idx, "flatten"

        return None

    def _fallback_exit_index(self, candles: List[Dict[str, Any]], buy_idx: int) -> int:
        """在未找到卖点时返回兜底索引"""
        if not candles:
            return 0
        if buy_idx < len(candles) - 1:
            return len(candles) - 1
        return buy_idx

    def _calc_slope(self, candles: List[Dict[str, Any]], end_idx: int, window: int) -> float:
        """估算窗口内的收盘价斜率"""
        if not candles or end_idx <= 0:
            return 0.0

        window = max(2, window)
        start_idx = max(0, end_idx - window + 1)
        if start_idx >= end_idx:
            return 0.0

        start_close = candles[start_idx]["close"]
        end_close = candles[end_idx]["close"]
        if start_close == 0:
            return 0.0

        change_ratio = (end_close - start_close) / start_close
        period = end_idx - start_idx
        if period <= 0:
            return 0.0
        return change_ratio / period

    def _has_long_upper_shadow(self, candle: Dict[str, Any], min_ratio: float) -> bool:
        """检测长上影线"""
        high = candle.get("high", 0.0)
        low = candle.get("low", 0.0)
        open_ = candle.get("open", 0.0)
        close = candle.get("close", 0.0)

        total_range = high - low
        if total_range <= 0:
            return False

        upper_shadow = high - max(open_, close)
        if upper_shadow <= 0:
            return False

        return (upper_shadow / total_range) >= min_ratio


class ZigZagWavePeaksValleysStrategy:
    """ZigZag波峰波谷检测策略"""

    def __init__(
        self,
        min_reversal: float = 0.05,
        *,
        retest_tolerance: float = 0.012,
        uptrend_window: int = 5,
        min_uptrend_slope: float = 0.0015,
        resistance_tolerance: float = 0.012,
        slowdown_window: int = 4,
        slowdown_slope: float = 0.0004,
        upper_shadow_ratio: float = 0.55,
        stop_loss_pct: float = 0.05,
        min_progress_pct: float = 0.03,
    ):
        """
        初始化ZigZag策略

        Args:
            min_reversal: 最小反转百分比 (默认5%)
            retest_tolerance: 回踩波谷的价格容差
            uptrend_window: 判断回踩后上涨趋势的窗口长度
            min_uptrend_slope: 视为有效上涨的最小斜率
            resistance_tolerance: 再次触及压力位的价格容差
            slowdown_window: 判断上涨放缓的窗口长度
            slowdown_slope: 放缓判定的最大斜率阈值
            upper_shadow_ratio: 长上影线占K线总体长度的比率阈值
            stop_loss_pct: 跌破波谷触发止损的百分比
            min_progress_pct: 视为趋势展开所需的最低涨幅，用于触发走平止盈判定
        """
        if not HAS_DATA_LOADER:
            raise ImportError("缺少 data_loader 模块")
        self.min_reversal = min_reversal
        self.retest_tolerance = retest_tolerance
        self.uptrend_window = uptrend_window
        self.min_uptrend_slope = min_uptrend_slope
        self.resistance_tolerance = resistance_tolerance
        self.slowdown_window = slowdown_window
        self.slowdown_slope = slowdown_slope
        self.upper_shadow_ratio = upper_shadow_ratio
        self.stop_loss_pct = stop_loss_pct
        self.min_progress_pct = min_progress_pct

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

        # 生成标记（仅买卖点与其上下文）
        markers: List[Dict[str, Any]] = []
        trade_markers, buy_count, sell_count, exit_stats = analyzer.generate_trade_markers(
            peaks,
            valleys,
            candles,
            retest_tolerance=self.retest_tolerance,
            uptrend_window=self.uptrend_window,
            min_uptrend_slope=self.min_uptrend_slope,
            resistance_tolerance=self.resistance_tolerance,
            slowdown_window=self.slowdown_window,
            slowdown_slope=self.slowdown_slope,
            upper_shadow_ratio=self.upper_shadow_ratio,
            stop_loss_pct=self.stop_loss_pct,
            min_progress_pct=self.min_progress_pct,
        )

        markers.extend(trade_markers)
        if len(markers) > 300:
            markers = sorted(markers, key=lambda m: m.get("time", ""), reverse=True)[:300]

        # 统计信息
        status_parts = [f"回踩买点 {buy_count} 个"]
        completed_sells = sell_count - exit_stats.get("pending", 0)
        if completed_sells > 0:
            status_parts.append(f"卖出 {completed_sells} 个")
        if exit_stats.get("pending"):
            status_parts.append(f"待确认 {exit_stats['pending']} 个")

        exit_labels = [
            ("stop", "止损"),
            ("resistance", "压力"),
            ("upper_shadow", "长上影"),
            ("flatten", "走平"),
        ]
        exit_summary = [f"{label_cn} {exit_stats[key]} 个" for key, label_cn in exit_labels if exit_stats.get(key)]
        if exit_summary:
            status_parts.append("，".join(exit_summary))
        status_message = "；".join(status_parts)

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


def run_zigzag_workbench(context: "StrategyContext") -> "StrategyRunResult":
    if StrategyContext is None or StrategyRunResult is None:
        raise RuntimeError("策略运行环境不可用")
    params = context.params or {}

    def _get_float(key: str, default: float) -> float:
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            return default

    def _get_int(key: str, default: int) -> int:
        try:
            return int(float(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    min_pct = _get_float("min_reversal", 5.0)
    min_reversal = max(0.0005, min_pct / 100.0)

    retest_pct = _get_float("retest_tolerance_pct", 1.2)
    retest_tolerance = max(0.0, retest_pct / 100.0)

    uptrend_window = max(2, _get_int("uptrend_window", 5))
    slope_pct = _get_float("min_uptrend_slope_pct", 0.15)
    min_uptrend_slope = max(0.0, slope_pct / 100.0)

    resistance_pct = _get_float("resistance_tolerance_pct", 1.2)
    resistance_tolerance = max(0.0, resistance_pct / 100.0)

    slowdown_window = max(2, _get_int("slowdown_window", 4))
    slowdown_slope_pct = _get_float("slowdown_slope_pct", 0.04)
    slowdown_slope = max(0.0, slowdown_slope_pct / 100.0)

    upper_shadow_pct = _get_float("upper_shadow_ratio_pct", 55.0)
    upper_shadow_ratio = min(0.99, max(0.0, upper_shadow_pct / 100.0))

    stop_loss_pct_input = _get_float("stop_loss_pct", 5.0)
    stop_loss_fraction = max(0.0, stop_loss_pct_input / 100.0)

    min_progress_pct_input = _get_float("min_progress_pct", 3.0)
    min_progress_fraction = max(0.0, min_progress_pct_input / 100.0)

    strategy = ZigZagWavePeaksValleysStrategy(
        min_reversal=min_reversal,
        retest_tolerance=retest_tolerance,
        uptrend_window=uptrend_window,
        min_uptrend_slope=min_uptrend_slope,
        resistance_tolerance=resistance_tolerance,
        slowdown_window=slowdown_window,
        slowdown_slope=slowdown_slope,
        upper_shadow_ratio=upper_shadow_ratio,
        stop_loss_pct=stop_loss_fraction,
        min_progress_pct=min_progress_fraction,
    )
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result("zigzag_wave_peaks_valleys", raw_result)