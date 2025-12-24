from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ..data.data_loader import load_candles_from_sqlite
except Exception:  # pragma: no cover
    load_candles_from_sqlite = None

try:
    from ..displays import DisplayResult  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    DisplayResult = None

try:
    from ..research import StrategyContext, StrategyRunResult
    from ..research.models import StrategyParameter
except Exception:  # pragma: no cover
    StrategyContext = None
    StrategyRunResult = None
    StrategyParameter = None

from .zigzag_wave_peaks_valleys import ZigZagWavePeaksValleysStrategy, ZIGZAG_STRATEGY_PARAMETERS
from .helpers import serialize_run_result


ZIGZAG_DOUBLE_RETEST_PARAMETERS: List["StrategyParameter"] = []
if StrategyParameter is not None:
    base_params = list(ZIGZAG_STRATEGY_PARAMETERS) if 'ZIGZAG_STRATEGY_PARAMETERS' in globals() else []
    ZIGZAG_DOUBLE_RETEST_PARAMETERS = base_params + [
        StrategyParameter(
            key="nested_confirm_rebound_pct",
            label="二次回踩反弹确认(%)",
            type="number",
            default=3.0,
            description="二次回踩后至少反弹该比例才买入（默认≥3%）。",
        ),
    ]


class ZigZagDoubleRetestStrategy(ZigZagWavePeaksValleysStrategy):
    """主波段回踩后，再出现二次回踩并反弹买入。"""

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
        nested_confirm_rebound_pct: float = 3.0,
    ) -> None:
        super().__init__(
            min_reversal_pct=min_reversal_pct,
            major_reversal_pct=major_reversal_pct,
            pivot_depth=pivot_depth,
            retest_tolerance_pct=retest_tolerance_pct,
            stop_loss_pct=stop_loss_pct,
            drawdown_take_profit_pct=drawdown_take_profit_pct,
            long_upper_shadow_pct=long_upper_shadow_pct,
            confirm_break_level=confirm_break_level,
            confirm_bullish_candle=confirm_bullish_candle,
            support_lookback_bars=support_lookback_bars,
            support_band_pct=support_band_pct,
        )
        self.nested_confirm_rebound = max(0.03, float(nested_confirm_rebound_pct) / 100.0)

    def scan_current_symbol(
        self,
        db_path: Path,
        table_name: str,
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Optional[Any]:
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"Unable to load candles for symbol {table_name}")
        candles, _volumes, _instrument = data
        candles = [c or {} for c in candles] if candles else []
        if not candles:
            return None

        pivots = self._detect_pivots(candles, self.min_reversal, self.pivot_depth)
        major_pivots = self._detect_pivots(candles, self.major_reversal, max(1, self.pivot_depth))
        if not pivots and candles:
            pivots = [
                {"index": 0, "type": "valley"},
                {"index": len(candles) - 1, "type": "peak"},
            ]

        trades = self._detect_double_retests(candles, pivots, major_pivots)
        pivot_markers = self._pivot_markers(pivots, candles) if pivots else []
        trade_markers = self._trade_markers(trades) if trades else []
        markers = pivot_markers + trade_markers
        overlays: List[Dict[str, Any]] = []
        open_trades = sum(1 for t in trades if not t.get("exit_time"))
        status_message = f"双回踩交易 {len(trades)}，持仓中 {open_trades}"
        strokes = self._retest_strokes(trades, candles)
        major_wave_lines = self._major_wave_strokes(candles, major_pivots, pivots)
        overlays = strokes + major_wave_lines
        status_message = f"{status_message}；主波段线 {len(major_wave_lines)}"
        scan_candidates: List[Dict[str, Any]] = []
        for t in trades:
            entry_time = t.get("entry_time")
            entry_price = t.get("entry_price")
            if entry_time is not None and entry_price is not None:
                scan_candidates.append(
                    {"date": entry_time, "price": entry_price, "score": 1.0, "note": "买入信号"}
                )
        extra_data: Dict[str, Any] = {
            "pivots": pivots,
            "trades": trades,
            "strokes": strokes,
            "major_wave_lines": major_wave_lines,
            "scan_candidates": scan_candidates,
            "instrument": {"name": _instrument.get("name") if isinstance(_instrument, dict) else ""},
            "skip_marker_fallback": True,
        }

        if DisplayResult is not None:
            return DisplayResult(
                strategy_name="zigzag_double_retest",
                markers=markers,
                overlays=overlays,
                status_message=status_message,
                extra_data=extra_data,
            )
        return {
            "strategy_name": "zigzag_double_retest",
            "markers": markers,
            "overlays": overlays,
            "status_message": status_message,
            "extra_data": extra_data,
        }

    def _detect_double_retests(
        self,
        candles: List[Dict[str, Any]],
        pivots: List[Dict[str, Any]],
        major_pivots: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not candles or len(major_pivots) < 2 or self.retest_tolerance <= 0:
            return []

        trades: List[Dict[str, Any]] = []
        tolerance = self.retest_tolerance
        stop_pct = self.stop_loss_pct
        upper_shadow_pct = self.long_upper_shadow_pct
        drawdown_take_profit = self.drawdown_take_profit
        confirm_rebound = self.nested_confirm_rebound

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

            first_retest: Optional[Dict[str, Any]] = None
            active_entry: Optional[Dict[str, Any]] = None

            for idx in range(peak_idx + 1, len(candles)):
                candle = candles[idx]
                close_price = float(candle.get("close", 0) or 0)
                low_price = float(candle.get("low", close_price) or 0)
                high_price = float(candle.get("high", close_price) or 0)
                open_price = float(candle.get("open", close_price) or close_price)
                time_value = candle.get("time", idx)

                if active_entry is None:
                    if low_price < overshoot_floor:
                        break
                    # 记录首次回踩
                    if first_retest is None and low_price <= entry_zone and low_price > stop_price:
                        first_retest = {
                            "index": idx,
                            "time": time_value,
                            "price": low_price,
                            "high": high_price,
                        }
                        continue
                    # 第二次回踩+反弹满足确认，触发买入
                    if first_retest is not None and low_price <= entry_zone and low_price > stop_price:
                        rebound_ok = first_retest["price"] > 0 and ((close_price - first_retest["price"]) / first_retest["price"]) >= confirm_rebound
                        bullish_ok = (not self.confirm_bullish_candle) or (close_price > open_price)
                        if rebound_ok and bullish_ok:
                            active_entry = {
                                "entry_time": time_value,
                                "entry_index": idx,
                                "entry_price": close_price,
                                "entry_reason": "双回踩买入",
                                "stop_price": stop_price,
                                "anchor_price": valley_price,
                                "anchor_time": valley_time,
                                "anchor_index": valley_idx,
                                "anchor_kind": "valley",
                                "retest_time": first_retest.get("time"),
                                "retest_index": first_retest.get("index"),
                                "retest_price": first_retest.get("price"),
                                "retest_high": first_retest.get("high"),
                            }
                        continue
                # 持仓管理
                if active_entry is not None:
                    if low_price <= active_entry["stop_price"]:
                        trades.append(
                            {
                                **active_entry,
                                "exit_time": time_value,
                                "exit_index": idx,
                                "exit_price": active_entry["stop_price"],
                                "exit_reason": "止损卖出",
                            }
                        )
                        active_entry = None
                        break
                    if drawdown_take_profit > 0:
                        active_entry.setdefault("max_price_seen", active_entry["entry_price"])
                        max_price_seen = max(active_entry["max_price_seen"], high_price)
                        active_entry["max_price_seen"] = max_price_seen
                        if max_price_seen > 0 and close_price <= max_price_seen * (1.0 - drawdown_take_profit):
                            trades.append(
                                {
                                    **active_entry,
                                    "exit_time": time_value,
                                    "exit_index": idx,
                                    "exit_price": close_price,
                                    "exit_reason": "回撤止盈卖出",
                                }
                            )
                            active_entry = None
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
                                    "exit_reason": "长上影止盈卖出",
                                }
                            )
                            active_entry = None
                            break

            if active_entry is not None:
                last_candle = candles[-1] if candles else {}
                last_time = last_candle.get("time", len(candles) - 1)
                last_close = float(last_candle.get("close", 0) or 0)
                exit_price = last_close if last_close > 0 else active_entry.get("entry_price")
                trades.append(
                    {
                        **active_entry,
                        "exit_time": last_time,
                        "exit_index": len(candles) - 1,
                        "exit_price": exit_price,
                        "exit_reason": "持仓结束",
                    }
                )
        return trades


def run_zigzag_double_retest_workbench(context: "StrategyContext") -> "StrategyRunResult":
    if StrategyContext is None or StrategyRunResult is None:
        raise RuntimeError("Strategy runtime not available.")
    params = dict(context.params or {})
    strategy = ZigZagDoubleRetestStrategy(
        min_reversal_pct=float(params.get("min_reversal_pct", 5.0) or 5.0),
        major_reversal_pct=float(params.get("major_reversal_pct", 12.0) or 12.0),
        pivot_depth=int(float(params.get("pivot_depth", 1) or 1)),
        retest_tolerance_pct=float(params.get("retest_tolerance_pct", 1.5) or 1.5),
        stop_loss_pct=float(params.get("stop_loss_pct", 2.0) or 2.0),
        drawdown_take_profit_pct=float(params.get("drawdown_take_profit_pct", 7.0) or 7.0),
        long_upper_shadow_pct=float(params.get("long_upper_shadow_pct", 3.0) or 3.0),
        confirm_break_level=bool(int(float(params.get("confirm_break_level", 1) or 1))),
        confirm_bullish_candle=bool(int(float(params.get("confirm_bullish_candle", 1) or 1))),
        support_lookback_bars=int(float(params.get("support_lookback_bars", 180) or 180)),
        support_band_pct=float(params.get("support_band_pct", 1.0) or 1.0),
        nested_confirm_rebound_pct=float(params.get("nested_confirm_rebound_pct", 3.0) or 3.0),
    )
    raw_result = strategy.scan_current_symbol(
        context.db_path,
        context.table_name,
        start_date=context.start_date,
        end_date=context.end_date,
    )
    return serialize_run_result("zigzag_double_retest", raw_result)


__all__ = [
    "ZigZagDoubleRetestStrategy",
    "ZIGZAG_DOUBLE_RETEST_PARAMETERS",
    "run_zigzag_double_retest_workbench",
]
