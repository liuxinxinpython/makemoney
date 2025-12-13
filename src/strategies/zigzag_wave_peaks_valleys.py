from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from ..data.data_loader import load_candles_from_sqlite
    HAS_DATA_LOADER = True
except Exception:  # pragma: no cover - optional import
    load_candles_from_sqlite = None
    HAS_DATA_LOADER = False

try:
    from ..displays import DisplayResult  # type: ignore[import-not-found]
    HAS_DISPLAY = True
except Exception:  # pragma: no cover - optional import
    DisplayResult = None
    HAS_DISPLAY = False

try:
    from ..research import StrategyContext, StrategyRunResult
    from ..research.models import StrategyParameter
except Exception:  # pragma: no cover - optional import
    StrategyContext = None
    StrategyRunResult = None
    StrategyParameter = None

from .helpers import serialize_run_result

# UI metadata for the workbench parameter panel.
ZIGZAG_STRATEGY_PARAMETERS: List[StrategyParameter] = []
if StrategyParameter is not None:
    ZIGZAG_STRATEGY_PARAMETERS = [
        StrategyParameter(
            key="min_reversal_pct",
            label="最小反转 (%)",
            type="number",
            default=6.0,
            description="价格至少反转该百分比才确认新枢轴。",
        ),
        StrategyParameter(
            key="major_reversal_pct",
            label="主波段反转阈值 (%)",
            type="number",
            default=12.0,
            description="大级别 ZigZag 反转阈值，用于划分主波段（父浪）；回踩/买点仅在主波段内识别。",
        ),
        StrategyParameter(
            key="pivot_depth",
            label="枢轴深度(根数)",
            type="number",
            default=1,
            description="经典 ZigZag 深度，枢轴需与前一个至少间隔这么多K线，过近则替换为更极值。（主波段与普通枢轴共用）",
        ),
        StrategyParameter(
            key="retest_tolerance_pct",
            label="回踩容差 (%)",
            type="number",
            default=1.5,
            description="回踩到距上一个波谷该百分比内，视作买入触发区。",
        ),
        StrategyParameter(
            key="stop_loss_pct",
            label="止损(相对波谷) (%)",
            type="number",
            default=2.0,
            description="回踩买入的硬止损，按波谷收盘向下百分比计算。",
        ),
        StrategyParameter(
            key="take_profit_r",
            label="止盈 (R 倍)",
            type="number",
            default=2.0,
            description="按止损距离的 R 倍止盈；设为 0 关闭。",
        ),
        StrategyParameter(
            key="long_upper_shadow_pct",
            label="长上影止盈 (%)",
            type="number",
            default=3.0,
            description="如果当日上影长度占收盘价比例超过该值则止盈（0 关闭）。",
        ),
        StrategyParameter(
            key="support_lookback_bars",
            label="支撑查找回溯K线数",
            type="number",
            default=180,
            description="向后查找密集支撑区的K线数量。",
        ),
        StrategyParameter(
            key="support_band_pct",
            label="支撑密集带宽 (%)",
            type="number",
            default=1.0,
            description="定义密集区价带宽度（±该百分比）。",
        ),
        StrategyParameter(
            key="confirm_break_level",
            label="确认：突破回踩高点(0/1)",
            type="number",
            default=1,
            description="回踩后需突破回踩K线的最高价才买入。",
        ),
        StrategyParameter(
            key="confirm_bullish_candle",
            label="确认：阳线或吞没(0/1)",
            type="number",
            default=1,
            description="回踩后需出现阳线（收盘>开盘）或实体大于前一根实体。",
        ),
    ]


class ZigZagWavePeaksValleysStrategy:
    """
    ZigZag 波峰波谷识别：用最小反转幅度在收盘价上寻找波峰/波谷，
    并给波谷/波峰分别打出买入/卖出标记。

    扩展了“回踩波谷 + 止损”玩法：波谷确认后走出波峰，回踩到波谷上方容差区且未破止损时买入，
    止损放在波谷下方，可选按 R 倍止盈。
    """

    def __init__(
        self,
        min_reversal_pct: float = 5.0,
        major_reversal_pct: float = 12.0,
        pivot_depth: int = 1,
        retest_tolerance_pct: float = 1.5,
        stop_loss_pct: float = 2.0,
        take_profit_r: float = 2.0,
        long_upper_shadow_pct: float = 3.0,
        confirm_break_level: bool = True,
        confirm_bullish_candle: bool = True,
        support_lookback_bars: int = 180,
        support_band_pct: float = 1.0,
    ) -> None:
        if not HAS_DATA_LOADER:
            raise ImportError("Missing data_loader module; cannot load candles.")
        # Convert percent to fraction; enforce a tiny floor to avoid division by zero.
        self.min_reversal = max(0.0005, float(min_reversal_pct) / 100.0)
        self.major_reversal = max(self.min_reversal, float(major_reversal_pct) / 100.0)
        self.pivot_depth = max(1, int(pivot_depth))
        self.retest_tolerance = max(0.0, float(retest_tolerance_pct) / 100.0)
        self.stop_loss_pct = max(0.0005, float(stop_loss_pct) / 100.0)
        self.take_profit_r = max(0.0, float(take_profit_r))
        self.long_upper_shadow_pct = max(0.0, float(long_upper_shadow_pct) / 100.0)
        self.confirm_break_level = bool(confirm_break_level)
        self.confirm_bullish_candle = bool(confirm_bullish_candle)
        self.support_lookback_bars = max(10, int(support_lookback_bars or 0))
        self.support_band = max(0.0005, float(support_band_pct) / 100.0)

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional[Any]:
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"Unable to load candles for symbol {table_name}")
        candles, _volumes, _instrument = data

        pivots = self._detect_pivots(candles, self.min_reversal, self.pivot_depth)
        major_pivots = self._detect_pivots(candles, self.major_reversal, max(1, self.pivot_depth))
        # Fallback so preview always shows at least one buy/sell pair.
        if not pivots and candles:
            pivots = [
                {"index": 0, "type": "valley"},
                {"index": len(candles) - 1, "type": "peak"},
            ]

        # 暂停买点与相关标记，仅展示波峰波谷和主波段
        trades: List[Dict[str, Any]] = []
        pivot_markers = self._pivot_markers(pivots, candles) if pivots else []
        markers = pivot_markers
        overlays: List[Dict[str, Any]] = []
        open_trades = 0
        status_message = "仅显示波峰波谷与主波段"
        strokes: List[Dict[str, Any]] = []
        major_wave_lines = self._major_wave_strokes(candles, major_pivots, pivots)
        overlays = strokes + major_wave_lines
        status_message = f"{status_message}；主波段线 {len(major_wave_lines)}"
        extra_data: Dict[str, Any] = {"pivots": pivots, "trades": trades, "strokes": strokes, "major_wave_lines": major_wave_lines}

        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name="zigzag_wave_peaks_valleys",
                markers=markers,
                overlays=overlays,
                status_message=status_message,
                extra_data=extra_data,
            )
        return {
            "strategy_name": "zigzag_wave_peaks_valleys",
            "markers": markers,
            "overlays": overlays,
            "status_message": status_message,
            "extra_data": extra_data,
        }

    def _find_support_zone(
        self,
        candles: List[Dict[str, Any]],
        start: int,
        end: int,
    ) -> Optional[Tuple[float, int, Any]]:
        """
        在父浪区间内粗略找一个近端密集支撑区：
        取 [start, end] 范围内的收盘价，中位数为中心，带宽为 support_band 的区间，
        取最后一次落在区间内的 K 线作为支撑锚点。
        """
        if end < start:
            return None
        closes = [float(candles[i].get("close", 0) or 0) for i in range(start, end + 1)]
        closes = [c for c in closes if c > 0]
        if not closes:
            return None
        closes_sorted = sorted(closes)
        mid = closes_sorted[len(closes_sorted) // 2]
        band = max(0.0005, mid * self.support_band)
        lower = mid - band
        upper = mid + band
        anchor_idx = None
        anchor_price = None
        for idx in range(end, start - 1, -1):
            close_price = float(candles[idx].get("close", 0) or 0)
            if lower <= close_price <= upper:
                anchor_idx = idx
                anchor_price = close_price
                break
        if anchor_idx is None or anchor_price is None:
            return None
        anchor_time = candles[anchor_idx].get("time", anchor_idx)
        return anchor_price, anchor_idx, anchor_time

    @staticmethod
    def _detect_pivots(
        candles: List[Dict[str, Any]],
        min_reversal: float,
        depth: int,
    ) -> List[Dict[str, Any]]:
        """
        更贴近经典 ZigZag（百分比，高低价）：
        - 初始方向未定，只有当涨/跌幅超过阈值才确立方向并记下首个枢轴；
        - 向上段记录最高点，回落超阈确认为波峰；向下段记录最低点，反弹超阈确认为波谷；
        - 枢轴间隔小于 depth 时，用更极值替换，避免过近/同根重复。
        """
        if len(candles) < max(3, depth + 1):
            return []

        highs = [float(c.get("high", c.get("close", 0)) or 0) for c in candles]
        lows = [float(c.get("low", c.get("close", 0)) or 0) for c in candles]

        pivots: List[Dict[str, Any]] = []
        direction = 0  # 1 up, -1 down, 0 unknown
        last_pivot_idx = 0
        last_pivot_price = (highs[0] + lows[0]) / 2 if highs and lows else 0.0
        extreme_idx = 0
        extreme_price = last_pivot_price

        def add_pivot(idx: int, kind: str) -> None:
            if not pivots:
                pivots.append({"index": idx, "type": kind})
                return
            last = pivots[-1]
            if idx - last["index"] < depth:
                if kind == "peak" and highs[idx] > highs[last["index"]]:
                    pivots[-1] = {"index": idx, "type": kind}
                elif kind == "valley" and lows[idx] < lows[last["index"]]:
                    pivots[-1] = {"index": idx, "type": kind}
            else:
                if last["type"] == kind:
                    if (kind == "peak" and highs[idx] > highs[last["index"]]) or (
                        kind == "valley" and lows[idx] < lows[last["index"]]
                    ):
                        pivots[-1] = {"index": idx, "type": kind}
                else:
                    pivots.append({"index": idx, "type": kind})

        for idx in range(1, len(candles)):
            hi = highs[idx]
            lo = lows[idx]

            if direction == 0:
                up_move = (hi - last_pivot_price) / last_pivot_price if last_pivot_price else 0.0
                down_move = (last_pivot_price - lo) / last_pivot_price if last_pivot_price else 0.0
                if up_move >= min_reversal:
                    # 初始向上，首个枢轴是 valley
                    add_pivot(last_pivot_idx, "valley")
                    direction = 1
                    extreme_idx = idx
                    extreme_price = hi
                elif down_move >= min_reversal:
                    add_pivot(last_pivot_idx, "peak")
                    direction = -1
                    extreme_idx = idx
                    extreme_price = lo
                else:
                    if hi > extreme_price:
                        extreme_price = hi
                        extreme_idx = idx
                    if lo < extreme_price:
                        extreme_price = lo
                        extreme_idx = idx
                continue

            if direction == 1:
                if hi > extreme_price:
                    extreme_price = hi
                    extreme_idx = idx
                drawdown = (extreme_price - lo) / extreme_price if extreme_price else 0.0
                if drawdown >= min_reversal:
                    add_pivot(extreme_idx, "peak")
                    direction = -1
                    last_pivot_idx = extreme_idx
                    last_pivot_price = extreme_price
                    extreme_idx = idx
                    extreme_price = lo
                    continue

            if direction == -1:
                if lo < extreme_price:
                    extreme_price = lo
                    extreme_idx = idx
                rebound = (hi - extreme_price) / extreme_price if extreme_price else 0.0
                if rebound >= min_reversal:
                    add_pivot(extreme_idx, "valley")
                    direction = 1
                    last_pivot_idx = extreme_idx
                    last_pivot_price = extreme_price
                    extreme_idx = idx
                    extreme_price = hi
                    continue

        # 收尾：将最后一个极值作为当前方向的枢轴，并用最后一根收口
        if direction == 1:
            add_pivot(extreme_idx, "peak")
        elif direction == -1:
            add_pivot(extreme_idx, "valley")

        if pivots:
            last = pivots[-1]
            if last["index"] != len(candles) - 1:
                pivots.append(
                    {
                        "index": len(candles) - 1,
                        "type": "peak" if last["type"] == "valley" else "valley",
                    }
                )
        return pivots

    @staticmethod
    def _pivot_markers(pivots: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        markers: List[Dict[str, Any]] = []
        for idx, pivot in enumerate(pivots):
            c = candles[pivot["index"]]
            is_valley = pivot["type"] == "valley"
            price = float(c.get("low", 0) or c.get("close", 0) or 0) if is_valley else float(c.get("high", 0) or c.get("close", 0) or 0)
            markers.append(
                {
                    "id": f"zigzag_pivot_{idx}",
                    "time": c.get("time"),
                    "position": "belowBar" if is_valley else "aboveBar",
                    "color": "#22c55e" if is_valley else "#ef4444",
                    "shape": "arrowUp" if is_valley else "arrowDown",
                    "text": f"{'波谷' if is_valley else '波峰'} {price:.2f}",
                    "price": price,
                }
            )
        return markers

    def _detect_valley_retests(
        self,
        candles: List[Dict[str, Any]],
        pivots: List[Dict[str, Any]],
        major_pivots: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Find pullbacks that retest the last confirmed valley without peeking into future bars.

        Rules (single forward pass):
        1) Need a confirmed valley followed by a confirmed peak (zigzag already confirmed by past bars).
        2) After that peak, if price pulls back into the valley zone (within tolerance, not breaking stop)
           we open a long at close.
        3) Manage with hard stop below valley; take-profit at R multiple if configured.
        4) If bar breaks stop first, abandon setup; if target hits, exit; otherwise hold until end.
        """
        if not candles or len(major_pivots) < 2 or self.retest_tolerance <= 0:
            return []

        trades: List[Dict[str, Any]] = []
        tolerance = self.retest_tolerance
        stop_pct = self.stop_loss_pct
        take_profit_r = self.take_profit_r
        upper_shadow_pct = self.long_upper_shadow_pct

        def _iter_major_waves() -> List[Tuple[int, int, int]]:
            """
            主波段定义：大级别 ZigZag 相邻的 valley→peak 组成一段上升主波段。
            结束位置：该 peak 之后出现的第一个大级别 valley（如果没有，则至末尾）。
            """
            windows: List[Tuple[int, int, int]] = []
            use_pivots = major_pivots if len(major_pivots) >= 2 else pivots
            for i in range(len(use_pivots) - 1):
                first = use_pivots[i]
                second = use_pivots[i + 1]
                if first["type"] != "valley" or second["type"] != "peak":
                    continue
                valley_idx = first["index"]
                peak_idx = second["index"]
                if valley_idx >= peak_idx:
                    continue
                wave_end = len(candles) - 1
                for j in range(i + 2, len(use_pivots)):
                    if use_pivots[j]["type"] == "valley":
                        wave_end = use_pivots[j]["index"]
                        break
                if wave_end <= peak_idx:
                    continue
                windows.append((valley_idx, peak_idx, wave_end))
            return windows

        for valley_idx, peak_idx, window_end in _iter_major_waves():
            anchors: List[Tuple[float, int, Any, str]] = []
            valley_price = float(candles[valley_idx].get("low", candles[valley_idx].get("close", 0)) or 0)
            valley_time = candles[valley_idx].get("time", valley_idx)
            if valley_price > 0:
                anchors.append((valley_price, valley_idx, valley_time, "valley"))
            # 父浪内最近的次级波谷（抬升低点也可作为支撑）
            minor_valleys = [
                p for p in pivots if p.get("type") == "valley" and valley_idx < p["index"] <= window_end
            ]
            if minor_valleys:
                last_minor = minor_valleys[-1]
                mv_idx = last_minor["index"]
                mv_price = float(candles[mv_idx].get("low", candles[mv_idx].get("close", 0)) or 0)
                mv_time = candles[mv_idx].get("time", mv_idx)
                if mv_price > 0:
                    anchors.append((mv_price, mv_idx, mv_time, "minor_valley"))
            sup_start = valley_idx
            sup_end = min(window_end, valley_idx + self.support_lookback_bars)
            support = self._find_support_zone(candles, sup_start, sup_end)
            if support is not None:
                sup_price, sup_idx, sup_time = support
                anchors.append((sup_price, sup_idx, sup_time, "support"))

            for base_price, base_idx, base_time, base_kind in anchors:
                entry_zone = base_price * (1.0 + tolerance)
                stop_price = base_price * (1.0 - stop_pct)
                retest_index: Optional[int] = None
                retest_time: Optional[Any] = None
                retest_price: Optional[float] = None
                retest_high: Optional[float] = None
                active_entry: Optional[Dict[str, Any]] = None
                trade_recorded = False

                for idx in range(peak_idx + 1, window_end + 1):
                    candle = candles[idx]
                    close_price = float(candle.get("close", 0) or 0)
                    low_price = float(candle.get("low", close_price) or 0)
                    high_price = float(candle.get("high", close_price) or 0)
                    time_value = candle.get("time", idx)
                    prev_close = (
                        float(candles[idx - 1].get("close", close_price) or close_price) if idx > 0 else close_price
                    )
                    prev_high = (
                        float(candles[idx - 1].get("high", prev_close) or prev_close) if idx > 0 else close_price
                    )
                    open_price = float(candle.get("open", close_price) or close_price)

                    if active_entry is None:
                        if low_price <= stop_price:
                            retest_index = None
                            retest_time = None
                            retest_price = None
                            retest_high = None
                            continue
                        # 回踩到位用当日最低价判断，必须贴近波谷低点（容差区内）
                        if low_price <= entry_zone and low_price > stop_price:
                            retest_index = idx
                            retest_time = time_value
                            retest_price = low_price
                            retest_high = high_price
                            continue
                        # 反转确认：阳线/吞没，且突破回踩K线的高点
                        bullish_ok = (not self.confirm_bullish_candle) or (close_price > open_price)
                        level_to_break = retest_high if retest_high is not None else (retest_price if retest_price is not None else prev_high)
                        break_ok = (not self.confirm_break_level) or (
                            level_to_break is not None and high_price > level_to_break and close_price > level_to_break
                        )
                        confirm_by_break = (
                            retest_index is not None
                            and idx >= retest_index
                            and close_price > stop_price
                            and close_price > prev_close
                            and bullish_ok
                            and break_ok
                        )
                        # 额外的“站回锚点”宽松确认：回踩后若收盘重新站上锚点且未触发止损，也视为转向
                        confirm_by_reclaim = (
                            retest_index is not None
                            and idx > retest_index
                            and close_price >= base_price
                            and close_price > stop_price
                            and close_price > prev_close
                            and bullish_ok
                        )
                        if confirm_by_break or confirm_by_reclaim:
                            risk_perc = (close_price - stop_price) / close_price if close_price else stop_pct
                            target_price = (
                                close_price * (1.0 + take_profit_r * risk_perc) if take_profit_r > 0 else None
                            )
                            active_entry = {
                                "entry_time": time_value,
                                "entry_index": idx,
                                "entry_price": close_price,
                                "entry_reason": "回踩买入",
                                "stop_price": stop_price,
                                "target_price": target_price,
                                "anchor_price": base_price,
                                "anchor_time": base_time,
                                "anchor_index": base_idx,
                                "anchor_kind": base_kind,
                                "retest_time": retest_time,
                                "retest_index": retest_index,
                                "retest_price": retest_price,
                                "retest_high": retest_high,
                            }
                        continue

                    # manage open trade
                    if low_price <= active_entry["stop_price"]:
                        trades.append(
                            {
                                **active_entry,
                                "exit_time": time_value,
                                "exit_index": idx,
                                "exit_price": active_entry["stop_price"],
                                "exit_reason": "止损",
                            }
                        )
                        active_entry = None
                        retest_index = None
                        retest_time = None
                        retest_price = None
                        trade_recorded = True
                        break

                    target_price = active_entry.get("target_price")
                    if target_price is not None and high_price >= target_price:
                        trades.append(
                            {
                                **active_entry,
                                "exit_time": time_value,
                                "exit_index": idx,
                                "exit_price": target_price,
                                "exit_reason": f"止盈 {take_profit_r:.1f}R",
                            }
                        )
                        active_entry = None
                        retest_index = None
                        retest_time = None
                        retest_price = None
                        trade_recorded = True
                        break

                    if upper_shadow_pct > 0:
                        body_top = max(open_price, close_price)
                        upper_shadow_len = max(0.0, high_price - body_top)
                        if body_top > 0 and (upper_shadow_len / body_top) >= upper_shadow_pct:
                            trades.append(
                                {
                                    **active_entry,
                                    "exit_time": time_value,
                                    "exit_index": idx,
                                    "exit_price": close_price,
                                    "exit_reason": "长上影止盈",
                                }
                            )
                            active_entry = None
                            retest_index = None
                            retest_time = None
                            retest_price = None
                            trade_recorded = True
                            break

                if active_entry is not None:
                    trades.append({**active_entry, "exit_time": None, "exit_price": None, "exit_reason": "持仓中"})
                    trade_recorded = True

                if trade_recorded:
                    # 每个锚点只保留一笔回踩交易
                    continue

        return trades

    def _trade_markers(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert trade entries/exits to chart markers."""
        markers: List[Dict[str, Any]] = []
        for idx, trade in enumerate(trades):
            entry_time = trade.get("entry_time")
            exit_time = trade.get("exit_time")
            entry_price = trade.get("entry_price")
            exit_price = trade.get("exit_price")
            entry_index = trade.get("entry_index")
            exit_index = trade.get("exit_index")
            retest_time = trade.get("retest_time")
            retest_index = trade.get("retest_index")
            retest_price = trade.get("retest_price")
            anchor_time = trade.get("anchor_time")
            anchor_index = trade.get("anchor_index")
            anchor_price = trade.get("anchor_price")
            anchor_kind = trade.get("anchor_kind") or "anchor"

            def _time_or_index(time_value: Any, index_value: Any) -> Any:
                return time_value if time_value is not None else index_value

            if anchor_time is not None or anchor_index is not None:
                markers.append(
                    {
                        "id": f"anchor_{idx}",
                        "time": _time_or_index(anchor_time, anchor_index),
                        "position": "belowBar",
                        "color": "#38bdf8",
                        "shape": "circle",
                        "text": f"{'支撑' if anchor_kind=='support' else '波谷'} {anchor_price:.2f}" if anchor_price is not None else anchor_kind,
                        "price": anchor_price,
                    }
                )
            if retest_time is not None or retest_index is not None:
                markers.append(
                    {
                        "id": f"retest_touch_{idx}",
                        "time": _time_or_index(retest_time, retest_index),
                        "position": "inBar",  # 与买入点错位，避免同一根被覆盖
                        "color": "#94a3b8",
                        "shape": "circle",
                        "text": f"回踩到位 {retest_price:.2f}" if retest_price is not None else "回踩到位",
                        "price": retest_price,
                    }
                )
            if entry_time is not None or entry_index is not None:
                markers.append(
                    {
                        "id": f"retest_entry_{idx}",
                        "time": _time_or_index(entry_time, entry_index),
                        "position": "belowBar",
                        "color": "#0ea5e9",
                        "shape": "triangle",
                        "text": f"回踩买入 {entry_price:.2f}" if entry_price is not None else "回踩买入",
                        "price": entry_price,
                    }
                )
            if (exit_time is not None) or (exit_index is not None):
                markers.append(
                    {
                        "id": f"retest_exit_{idx}",
                        "time": _time_or_index(exit_time, exit_index),
                        "position": "aboveBar",
                        "color": "#f97316",
                        "shape": "triangle",
                        "text": f"卖出 {exit_price:.2f}" if exit_price is not None else "卖出",
                        "price": exit_price,
                    }
                )
        return markers

    def _retest_strokes(self, trades: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build line segments from anchor（波谷或支撑）到回踩触发点（回踩到位的K线），而非买入执行点."""
        strokes: List[Dict[str, Any]] = []
        for idx, trade in enumerate(trades):
            anchor_time = trade.get("anchor_time")
            retest_time = trade.get("retest_time")
            anchor_index = trade.get("anchor_index")
            retest_index = trade.get("retest_index")
            anchor_price = trade.get("anchor_price")
            retest_price = trade.get("retest_price")
            if anchor_time is None and anchor_index is None:
                continue
            if retest_time is None and retest_index is None:
                continue
            if isinstance(anchor_index, int) and isinstance(retest_index, int) and anchor_index > retest_index:
                # 若锚点索引在回踩之后，认为数据不可靠，跳过该连线
                continue
            start_time = anchor_time if anchor_time is not None else anchor_index
            end_time = retest_index if retest_index is not None else retest_time
            start_price = anchor_price
            if start_price is None and isinstance(anchor_index, int) and 0 <= anchor_index < len(candles):
                start_price = float(candles[anchor_index].get("close", 0) or 0)
            # 线条终点使用回踩触发K线的收盘价
            end_price = retest_price
            if end_price is None and isinstance(retest_index, int) and 0 <= retest_index < len(candles):
                end_price = float(candles[retest_index].get("close", 0) or 0)
            strokes.append(
                {
                    "startTime": start_time,
                    "endTime": end_time,
                    "startPrice": start_price,
                    "endPrice": end_price,
                    "direction": 1,
                    "kind": "retest_link",
                    "label": f"回踩连线#{idx+1}",
                }
            )
        return strokes

    def _major_wave_strokes(self, candles: List[Dict[str, Any]], major_pivots: List[Dict[str, Any]], fallback_pivots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将主波段的三个关键点（谷-峰-谷）用折线连接，便于可视化主波段范围。
        若大级别枢轴不足，则退回普通枢轴绘制，确保预览能看到主波段连线。
        """
        strokes: List[Dict[str, Any]] = []
        pivots_to_use = major_pivots if len(major_pivots) >= 2 else fallback_pivots
        if len(pivots_to_use) < 2:
            return strokes
        for i in range(len(pivots_to_use) - 1):
            first = pivots_to_use[i]
            second = pivots_to_use[i + 1]
            if first["type"] != "valley" or second["type"] != "peak":
                continue
            valley_idx = first["index"]
            peak_idx = second["index"]
            if valley_idx >= peak_idx:
                continue
            # 找到峰后的下一个大级别谷，若没有，则用末尾
            next_valley_idx = None
            for j in range(i + 2, len(pivots_to_use)):
                if pivots_to_use[j]["type"] == "valley":
                    next_valley_idx = pivots_to_use[j]["index"]
                    break
            end_idx = next_valley_idx if next_valley_idx is not None else (len(candles) - 1)
            if end_idx <= peak_idx:
                continue

            def _pt(idx: int, kind: str) -> Tuple[Any, float]:
                c = candles[idx]
                open_p = float(c.get("open", 0) or 0)
                close_p = float(c.get("close", 0) or 0)
                high_p = float(c.get("high", 0) or 0)
                low_p = float(c.get("low", 0) or 0)
                if kind == "valley":
                    price = min(open_p, close_p) if (open_p > 0 and close_p > 0) else (close_p or low_p)
                else:
                    price = max(open_p, close_p) if (open_p > 0 and close_p > 0) else (close_p or high_p)
                return c.get("time", idx), price

            v_time, v_price = _pt(valley_idx, "valley")
            p_time, p_price = _pt(peak_idx, "peak")
            e_time, e_price = _pt(end_idx, "valley")
            strokes.append(
                {
                    "startTime": v_time,
                    "endTime": p_time,
                    "startPrice": v_price,
                    "endPrice": p_price,
                    "direction": 1,
                    "kind": "major_wave",
                    "color": "#f59e0b",
                    "lineWidth": 2,
                    "lineStyle": "solid",
                    "label": f"主波段{len(strokes)+1}-1",
                }
            )
            strokes.append(
                {
                    "startTime": p_time,
                    "endTime": e_time,
                    "startPrice": p_price,
                    "endPrice": e_price,
                    "direction": -1,
                    "kind": "major_wave",
                    "color": "#f59e0b",
                    "lineWidth": 2,
                    "lineStyle": "solid",
                    "label": f"主波段{len(strokes)//2}-2",
                }
            )
        return strokes


def run_zigzag_workbench(context: "StrategyContext") -> "StrategyRunResult":
    if StrategyContext is None or StrategyRunResult is None:
        raise RuntimeError("Strategy runtime not available.")

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

    min_reversal_pct = _get_float("min_reversal_pct", 5.0)
    major_reversal_pct = _get_float("major_reversal_pct", 12.0)
    pivot_depth = _get_int("pivot_depth", 1)
    retest_tolerance_pct = _get_float("retest_tolerance_pct", 1.5)
    stop_loss_pct = _get_float("stop_loss_pct", 2.0)
    take_profit_r = _get_float("take_profit_r", 2.0)
    long_upper_shadow_pct = _get_float("long_upper_shadow_pct", 3.0)
    confirm_break_level = bool(_get_int("confirm_break_level", 1))
    confirm_bullish_candle = bool(_get_int("confirm_bullish_candle", 1))
    support_lookback_bars = _get_int("support_lookback_bars", 180)
    support_band_pct = _get_float("support_band_pct", 1.0)

    strategy = ZigZagWavePeaksValleysStrategy(
        min_reversal_pct=min_reversal_pct,
        major_reversal_pct=major_reversal_pct,
        pivot_depth=pivot_depth,
        retest_tolerance_pct=retest_tolerance_pct,
        stop_loss_pct=stop_loss_pct,
        take_profit_r=take_profit_r,
        long_upper_shadow_pct=long_upper_shadow_pct,
        confirm_break_level=confirm_break_level,
        confirm_bullish_candle=confirm_bullish_candle,
        support_lookback_bars=support_lookback_bars,
        support_band_pct=support_band_pct,
    )
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result("zigzag_wave_peaks_valleys", raw_result)


__all__ = ["ZigZagWavePeaksValleysStrategy", "ZIGZAG_STRATEGY_PARAMETERS", "run_zigzag_workbench"]
