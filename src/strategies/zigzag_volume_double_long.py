from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from ..data.data_loader import load_candles_from_sqlite
    HAS_DATA_LOADER = True
except Exception:  # pragma: no cover
    load_candles_from_sqlite = None
    HAS_DATA_LOADER = False

try:
    from ..displays import DisplayResult  # type: ignore[import-not-found]
    HAS_DISPLAY = True
except Exception:  # pragma: no cover
    DisplayResult = None
    HAS_DISPLAY = False

try:
    from ..research import StrategyContext, StrategyRunResult
    from ..research.models import StrategyParameter
except Exception:  # pragma: no cover
    StrategyContext = None
    StrategyRunResult = None
    StrategyParameter = None

from .helpers import serialize_run_result

# 参数定义
ZIGZAG_VOLUME_DOUBLE_LONG_PARAMETERS: List[StrategyParameter] = []
if StrategyParameter is not None:
    ZIGZAG_VOLUME_DOUBLE_LONG_PARAMETERS = [
        StrategyParameter("min_reversal_pct", "最小反转 (%)", "number", 6.0, "价格至少反转该百分比才确认新枢轴。"),
        StrategyParameter("major_reversal_pct", "主波段反转阈值 (%)", "number", 12.0, "大级别 ZigZag 反转阈值，用于划分主波段。"),
        StrategyParameter("pivot_depth", "枢轴深度(根数)", "number", 1, "枢轴需与前一个至少间隔这么多K线。"),
        StrategyParameter("retest_tolerance_pct", "回踩容差 (%)", "number", 1.5, "回踩到距上一个波谷该百分比内视作买入触发区。"),
        StrategyParameter("stop_loss_pct", "止损(回踩点) (%)", "number", 2.0, "买入后跌破回踩点该百分比止损。"),
        StrategyParameter("drawdown_take_profit_pct", "回撤止盈 (%)", "number", 7.0, "创高后回撤超过该百分比止盈；0 关闭。"),
        StrategyParameter("long_upper_shadow_pct", "长上影止盈 (%)", "number", 5.0, "上影占收盘比例超过该值止盈；0 关闭。"),
        StrategyParameter("support_lookback_bars", "支撑回溯K数", "number", 180, "向后查找密集支撑区的K线数量。"),
        StrategyParameter("support_band_pct", "支撑带宽 (%)", "number", 1.0, "定义支撑密集区价带宽度（±该百分比）。"),
        StrategyParameter("confirm_break_level", "确认：突破回踩高点(0/1)", "number", 1, "回踩后需突破回踩K线最高价才买入。"),
        StrategyParameter("confirm_bullish_candle", "确认：阳线或吞没(0/1)", "number", 1, "回踩后需出现阳线或实体大于前一根实体。"),
        StrategyParameter("volume_factor_first", "首阳倍量系数", "number", 1.8, "首根放量需达到回踩后最小量的倍数。"),
        StrategyParameter("volume_factor_second", "次阳倍量系数", "number", 1.8, "二次放量需达到回踩后最小量的倍数。"),
        StrategyParameter("avg_volume_window", "均量窗口", "number", 20, "均量备用窗口。"),
        StrategyParameter("post_retest_avg_window", "回踩后均量窗口", "number", 3, "回踩后短期均量窗口。"),
        StrategyParameter("pullback_pct", "首阳后最小回调(%)", "number", 1.0, "首阳后需回调/横盘该比例或至少隔两根。"),
    ]


class ZigZagVolumeDoubleLongStrategy:
    """
    波谷回踩 + 首阳放量 + 二次放量买入，骨架基于 zigzag_wave_peaks_valleys。
    """

    def __init__(
        self,
        min_reversal_pct: float = 5.0,
        major_reversal_pct: float = 12.0,
        pivot_depth: int = 1,
        retest_tolerance_pct: float = 1.5,
        stop_loss_pct: float = 2.0,
        drawdown_take_profit_pct: float = 7.0,
        long_upper_shadow_pct: float = 3.0,
        confirm_break_level: bool = True,
        confirm_bullish_candle: bool = True,
        support_lookback_bars: int = 180,
        support_band_pct: float = 1.0,
        volume_factor_first: float = 1.8,
        volume_factor_second: float = 1.8,
        avg_volume_window: int = 20,
        post_retest_avg_window: int = 3,
        pullback_pct: float = 1.0,
    ) -> None:
        if not HAS_DATA_LOADER:
            raise ImportError("Missing data_loader module; cannot load candles.")
        self.min_reversal = max(0.0005, float(min_reversal_pct) / 100.0)
        self.major_reversal = max(self.min_reversal, float(major_reversal_pct) / 100.0)
        self.pivot_depth = max(1, int(pivot_depth))
        self.retest_tolerance = max(0.0, float(retest_tolerance_pct) / 100.0)
        self.stop_loss_pct = max(0.0005, float(stop_loss_pct) / 100.0)
        self.drawdown_take_profit = max(0.0, float(drawdown_take_profit_pct) / 100.0)
        self.long_upper_shadow_pct = max(0.0, float(long_upper_shadow_pct) / 100.0)
        self.confirm_break_level = bool(confirm_break_level)
        self.confirm_bullish_candle = bool(confirm_bullish_candle)
        self.support_lookback_bars = max(10, int(support_lookback_bars or 0))
        self.support_band = max(0.0005, float(support_band_pct) / 100.0)
        self.vol_factor_first = max(1.0, float(volume_factor_first))
        self.vol_factor_second = max(1.0, float(volume_factor_second))
        self.avg_volume_window = max(5, int(avg_volume_window))
        self.post_retest_avg_window = max(1, int(post_retest_avg_window))
        self.pullback_pct = max(0.0, float(pullback_pct) / 100.0)

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional[Any]:
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"Unable to load candles for symbol {table_name}")
        candles, volumes, _instrument = data

        pivots = self._detect_pivots(candles, self.min_reversal, self.pivot_depth)
        major_pivots = self._detect_pivots(candles, self.major_reversal, max(1, self.pivot_depth))
        if not pivots and candles:
            pivots = [{"index": 0, "type": "valley"}, {"index": len(candles) - 1, "type": "peak"}]

        trades = self._detect_valley_retests(candles, volumes, pivots, major_pivots)
        pivot_markers = self._pivot_markers(pivots, candles) if pivots else []
        trade_markers = self._trade_markers(trades) if trades else []
        markers = pivot_markers + trade_markers
        strokes = self._retest_strokes(trades, candles)
        major_wave_lines = self._major_wave_strokes(candles, major_pivots, pivots)
        overlays = strokes + major_wave_lines
        open_trades = sum(1 for t in trades if not t.get("exit_time"))
        status_message = f"回踩交易 {len(trades)}，持仓中 {open_trades}；主波段线 {len(major_wave_lines)}"

        scan_candidates: List[Dict[str, Any]] = []
        for t in trades:
            et = t.get("entry_time")
            ep = t.get("entry_price")
            if et is not None and ep is not None:
                scan_candidates.append({"date": et, "price": ep, "score": 1.0, "note": "买入信号"})

        extra_data = {
            "pivots": pivots,
            "trades": trades,
            "strokes": strokes,
            "major_wave_lines": major_wave_lines,
            "scan_candidates": scan_candidates,
            "instrument": {"name": _instrument.get("name") if isinstance(_instrument, dict) else ""},
        }

        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name="zigzag_volume_double_long",
                markers=markers,
                overlays=overlays,
                status_message=status_message,
                extra_data=extra_data,
            )
        return {
            "strategy_name": "zigzag_volume_double_long",
            "markers": markers,
            "overlays": overlays,
            "status_message": status_message,
            "extra_data": extra_data,
        }

    # --- zigzag pivots（复制基础策略）
    @staticmethod
    def _detect_pivots(candles: List[Dict[str, Any]], min_reversal: float, depth: int) -> List[Dict[str, Any]]:
        if len(candles) < max(3, depth + 1):
            return []
        highs = [float(c.get("high", c.get("close", 0)) or 0) for c in candles]
        lows = [float(c.get("low", c.get("close", 0)) or 0) for c in candles]
        pivots: List[Dict[str, Any]] = []
        direction = 0
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
        if direction == 1:
            add_pivot(extreme_idx, "peak")
        elif direction == -1:
            add_pivot(extreme_idx, "valley")
        if pivots:
            last = pivots[-1]
            if last["index"] != len(candles) - 1:
                pivots.append({"index": len(candles) - 1, "type": "peak" if last["type"] == "valley" else "valley"})
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
        volumes: List[Dict[str, Any]],
        pivots: List[Dict[str, Any]],
        major_pivots: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not candles or len(major_pivots) < 2 or self.retest_tolerance <= 0:
            return []

        tolerance = self.retest_tolerance
        stop_pct = self.stop_loss_pct
        drawdown_take_profit = self.drawdown_take_profit
        upper_shadow_pct = self.long_upper_shadow_pct

        vol_list: List[float] = []
        for v in volumes or []:
            try:
                if isinstance(v, dict):
                    vol_list.append(float(v.get("volume", v.get("vol", v.get("value", v.get("amount", v.get("turnover", 0))))) or 0))
                else:
                    vol_list.append(float(v))
            except Exception:
                vol_list.append(0.0)
        if len(vol_list) < len(candles):
            vol_list.extend([0.0] * (len(candles) - len(vol_list)))
        else:
            vol_list = vol_list[: len(candles)]

        def avg_vol(idx: int) -> float:
            start = max(0, idx - self.avg_volume_window + 1)
            window = vol_list[start : idx + 1]
            return sum(window) / len(window) if window else 0.0

        def post_retest_min(idx: int, retest_idx: int) -> float:
            start = retest_idx + 1
            end = min(len(vol_list), idx + 1)
            window = vol_list[start:end]
            return min(window) if window else avg_vol(idx)

        trades: List[Dict[str, Any]] = []
        use_pivots = major_pivots if len(major_pivots) >= 2 else pivots
        for i in range(len(use_pivots) - 1):
            first = use_pivots[i]
            if first["type"] != "valley":
                continue
            peak_idx = None
            for j in range(i + 1, len(use_pivots)):
                if use_pivots[j]["type"] == "peak":
                    peak_idx = use_pivots[j]["index"]
                    break
            if peak_idx is None:
                continue

            valley_idx = first["index"]
            valley_price = float(candles[valley_idx].get("low", candles[valley_idx].get("close", 0)) or 0)
            valley_time = candles[valley_idx].get("time", valley_idx)
            if valley_price <= 0:
                continue

            entry_zone = valley_price * (1.0 + tolerance)
            stop_price = valley_price * (1.0 - stop_pct)
            overshoot_floor = valley_price * 0.95
            retest_index: Optional[int] = None
            retest_time: Optional[Any] = None
            retest_price: Optional[float] = None
            retest_high: Optional[float] = None
            first_vol_idx: Optional[int] = None
            first_vol_time: Optional[Any] = None
            first_vol_price: Optional[float] = None
            second_vol_time: Optional[Any] = None
            second_vol_price: Optional[float] = None
            second_vol_index: Optional[int] = None
            pullback_seen = False
            active_entry: Optional[Dict[str, Any]] = None

            for idx in range(peak_idx + 1, len(candles)):
                candle = candles[idx]
                close_price = float(candle.get("close", 0) or 0)
                low_price = float(candle.get("low", close_price) or 0)
                high_price = float(candle.get("high", close_price) or 0)
                open_price = float(candle.get("open", close_price) or close_price)
                time_value = candle.get("time", idx)
                vol = vol_list[idx] if idx < len(vol_list) else 0.0
                avgv = avg_vol(idx)

                if active_entry is None:
                    if low_price < overshoot_floor:
                        break
                    if retest_index is None and low_price <= entry_zone and low_price > stop_price:
                        retest_index = idx
                        retest_time = time_value
                        retest_price = low_price
                        retest_high = high_price
                        continue
                    if retest_index is None and stop_price >= low_price >= overshoot_floor:
                        retest_index = idx
                        retest_time = time_value
                        retest_price = low_price
                        retest_high = high_price
                        continue
                    if retest_index is not None and idx > retest_index:
                        if first_vol_idx is None:
                            bullish_ok = (not self.confirm_bullish_candle) or (close_price > open_price)
                            base_vol = post_retest_min(idx, retest_index) if retest_index is not None else avgv
                            vol_ok = True if base_vol <= 0 else (vol >= base_vol * self.vol_factor_first)
                            above_retest = retest_price is None or close_price > retest_price
                            # 放宽首阳位置：回踩确认后，首阳只需在回踩价之上且未跌破止损
                            in_play = (close_price > stop_price) and above_retest
                            if bullish_ok and vol_ok and in_play:
                                first_vol_idx = idx
                                first_vol_time = time_value
                                first_vol_price = close_price
                                continue
                        else:
                            first_close = float(candles[first_vol_idx].get("close", 0) or 0)
                            first_low = float(candles[first_vol_idx].get("low", first_close) or 0)
                            # 首阳后若再跌破回踩价，放弃本次回踩监控
                            if retest_price is not None and low_price < retest_price:
                                break
                            if not pullback_seen:
                                pullback_seen = (close_price < first_close * (1.0 - self.pullback_pct)) or (low_price < first_low * (1.0 - self.pullback_pct)) or (idx - first_vol_idx >= 2)
                                continue
                            bullish_ok = (not self.confirm_bullish_candle) or (close_price > open_price)
                            base_vol = post_retest_min(idx, retest_index) if retest_index is not None else avgv
                            vol_ok = True if base_vol <= 0 else (vol >= base_vol * self.vol_factor_second)
                            above_retest = retest_price is None or close_price > retest_price
                            if bullish_ok and vol_ok and close_price > stop_price and above_retest:
                                second_vol_time = time_value
                                second_vol_price = close_price
                                second_vol_index = idx
                                base_for_stop = retest_price if retest_price is not None else valley_price
                                entry_stop = base_for_stop * 0.98 if base_for_stop is not None else stop_price
                                active_entry = {
                                    "entry_time": time_value,
                                    "entry_index": idx,
                                    "entry_price": close_price,
                                    "entry_reason": "倍量买入",
                                    "stop_price": entry_stop,
                                    "anchor_price": valley_price,
                                    "anchor_time": valley_time,
                                    "anchor_index": valley_idx,
                                    "anchor_kind": "valley",
                                    "retest_time": retest_time,
                                    "retest_index": retest_index,
                                    "retest_price": retest_price,
                                    "retest_high": retest_high,
                                    "first_vol_index": first_vol_idx,
                                    "first_vol_time": first_vol_time,
                                    "first_vol_price": first_vol_price,
                                    "second_vol_index": second_vol_index,
                                    "second_vol_time": second_vol_time,
                                    "second_vol_price": second_vol_price,
                                }
                    continue

                if low_price <= active_entry["stop_price"]:
                    trades.append({**active_entry, "exit_time": time_value, "exit_index": idx, "exit_price": active_entry["stop_price"], "exit_reason": "止损卖出"})
                    active_entry = None
                    break
                if drawdown_take_profit > 0:
                    active_entry.setdefault("max_price_seen", active_entry["entry_price"])
                    max_price_seen = max(active_entry["max_price_seen"], high_price)
                    active_entry["max_price_seen"] = max_price_seen
                    if max_price_seen > 0 and close_price <= max_price_seen * (1.0 - drawdown_take_profit):
                        trades.append({**active_entry, "exit_time": time_value, "exit_index": idx, "exit_price": close_price, "exit_reason": "回撤止盈卖出"})
                        active_entry = None
                        break
                if upper_shadow_pct > 0:
                    body_top = max(open_price, close_price)
                    upper_shadow_len = max(0.0, high_price - body_top)
                    if body_top > 0 and (upper_shadow_len / body_top) >= upper_shadow_pct:
                        trades.append({**active_entry, "exit_time": time_value, "exit_index": idx, "exit_price": close_price, "exit_reason": "长上影止盈卖出"})
                        active_entry = None
                        break

            if active_entry is not None:
                trades.append({**active_entry, "exit_time": None, "exit_price": None, "exit_reason": "持仓中"})

        return trades

    def _trade_markers(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
            entry_reason = trade.get("entry_reason")
            exit_reason = trade.get("exit_reason")
            first_vol_time = trade.get("first_vol_time")
            first_vol_index = trade.get("first_vol_index")
            first_vol_price = trade.get("first_vol_price")
            second_vol_time = trade.get("second_vol_time")
            second_vol_index = trade.get("second_vol_index")
            second_vol_price = trade.get("second_vol_price")

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
                        "position": "inBar",
                        "color": "#94a3b8",
                        "shape": "circle",
                        "text": f"回踩到位 {retest_price:.2f}" if retest_price is not None else "回踩到位",
                        "price": retest_price,
                    }
                )
            if first_vol_time is not None or first_vol_index is not None:
                markers.append(
                    {
                        "id": f"first_vol_{idx}",
                        "time": _time_or_index(first_vol_time, first_vol_index),
                        "position": "aboveBar",
                        "color": "#f59e0b",
                        "shape": "circle",
                        "text": f"首阳放量 {first_vol_price:.2f}" if first_vol_price is not None else "首阳放量",
                        "price": first_vol_price,
                    }
                )
            if second_vol_time is not None or second_vol_index is not None:
                markers.append(
                    {
                        "id": f"second_vol_{idx}",
                        "time": _time_or_index(second_vol_time, second_vol_index),
                        "position": "aboveBar",
                        "color": "#fb923c",
                        "shape": "triangle",
                        "text": f"二次放量 {second_vol_price:.2f}" if second_vol_price is not None else "二次放量",
                        "price": second_vol_price,
                    }
                )
            if entry_time is not None or entry_index is not None:
                buy_text = entry_reason if isinstance(entry_reason, str) and entry_reason else (f"买入 {entry_price:.2f}" if entry_price is not None else "买入")
                markers.append(
                    {
                        "id": f"retest_entry_{idx}",
                        "time": _time_or_index(entry_time, entry_index),
                        "position": "belowBar",
                        "color": "#0ea5e9",
                        "shape": "triangle",
                        "text": buy_text,
                        "price": entry_price,
                    }
                )
            if exit_time is not None or exit_index is not None:
                reason = exit_reason or "卖出"
                markers.append(
                    {
                        "id": f"retest_exit_{idx}",
                        "time": _time_or_index(exit_time, exit_index),
                        "position": "aboveBar",
                        "color": "#f97316",
                        "shape": "triangle",
                        "text": f"{reason} {exit_price:.2f}" if exit_price is not None else reason,
                        "price": exit_price,
                    }
                )
        return markers

    def _retest_strokes(self, trades: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                continue
            start_time = anchor_time if anchor_time is not None else anchor_index
            end_time = retest_index if retest_index is not None else retest_time
            start_price = anchor_price
            if start_price is None and isinstance(anchor_index, int) and 0 <= anchor_index < len(candles):
                start_price = float(candles[anchor_index].get("close", 0) or 0)
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
            strokes.append({"startTime": v_time, "endTime": p_time, "startPrice": v_price, "endPrice": p_price, "direction": 1, "kind": "major_wave", "color": "#f59e0b", "lineWidth": 2, "lineStyle": "solid", "label": f"主波段{len(strokes)+1}-1"})
            strokes.append({"startTime": p_time, "endTime": e_time, "startPrice": p_price, "endPrice": e_price, "direction": -1, "kind": "major_wave", "color": "#f59e0b", "lineWidth": 2, "lineStyle": "solid", "label": f"主波段{len(strokes)//2}-2"})
        return strokes


def run_zigzag_volume_double_long_workbench(context: "StrategyContext") -> "StrategyRunResult":
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

    strategy = ZigZagVolumeDoubleLongStrategy(
        min_reversal_pct=_get_float("min_reversal_pct", 5.0),
        major_reversal_pct=_get_float("major_reversal_pct", 12.0),
        pivot_depth=_get_int("pivot_depth", 1),
        retest_tolerance_pct=_get_float("retest_tolerance_pct", 1.5),
        stop_loss_pct=_get_float("stop_loss_pct", 2.0),
        drawdown_take_profit_pct=_get_float("drawdown_take_profit_pct", 7.0),
        long_upper_shadow_pct=_get_float("long_upper_shadow_pct", 3.0),
        confirm_break_level=bool(_get_int("confirm_break_level", 1)),
        confirm_bullish_candle=bool(_get_int("confirm_bullish_candle", 1)),
        support_lookback_bars=_get_int("support_lookback_bars", 180),
        support_band_pct=_get_float("support_band_pct", 1.0),
        volume_factor_first=_get_float("volume_factor_first", 2.0),
        volume_factor_second=_get_float("volume_factor_second", 2.0),
        avg_volume_window=_get_int("avg_volume_window", 20),
        post_retest_avg_window=_get_int("post_retest_avg_window", 3),
        pullback_pct=_get_float("pullback_pct", 1.0),
    )
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result("zigzag_volume_double_long", raw_result)


__all__ = [
    "ZigZagVolumeDoubleLongStrategy",
    "ZIGZAG_VOLUME_DOUBLE_LONG_PARAMETERS",
    "run_zigzag_volume_double_long_workbench",
]
