from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from ..data.data_loader import load_candles_from_sqlite  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    load_candles_from_sqlite = None

try:
    from ..research import StrategyContext, StrategyRunResult
    from ..research.models import StrategyParameter
except Exception:  # pragma: no cover - optional dependency
    StrategyContext = None
    StrategyRunResult = None
    StrategyParameter = None

from .helpers import serialize_run_result


def _build_strategy_parameters() -> Dict[str, List[Any]]:
    if StrategyParameter is None:
        return {"ma": [], "rsi": [], "donchian": []}
    return {
        "ma": [
            StrategyParameter(
                key="short_window",
                label="Short window",
                type="number",
                default=20,
                description="Fast moving average window (e.g., 5/10/20).",
            ),
            StrategyParameter(
                key="long_window",
                label="Long window",
                type="number",
                default=50,
                description="Slow moving average window (e.g., 30/50/60).",
            ),
        ],
        "rsi": [
            StrategyParameter(
                key="period",
                label="RSI period",
                type="number",
                default=14,
                description="Lookback window for RSI calculation.",
            ),
            StrategyParameter(
                key="oversold",
                label="Oversold threshold",
                type="number",
                default=30.0,
                description="RSI below this triggers buy consideration.",
            ),
            StrategyParameter(
                key="overbought",
                label="Overbought threshold",
                type="number",
                default=70.0,
                description="RSI above this triggers sell consideration.",
            ),
        ],
        "donchian": [
            StrategyParameter(
                key="lookback",
                label="Lookback period",
                type="number",
                default=20,
                description="Window size to build Donchian channel.",
            ),
        ],
    }


PARAMETERS_BY_STRATEGY = _build_strategy_parameters()


def _assert_loader_available() -> None:
    if load_candles_from_sqlite is None:
        raise ImportError("Missing data_loader module; cannot load price data.")


def _load_symbol_data(db_path: Path, table_name: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    _assert_loader_available()
    data = load_candles_from_sqlite(db_path, table_name)
    if not data:
        raise ValueError(f"Unable to load history for {table_name}")
    return data


def _sma(values: List[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        raise ValueError("SMA window must be > 0")
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < window:
        return result
    rolling_sum = sum(values[:window])
    result[window - 1] = rolling_sum / window
    for idx in range(window, len(values)):
        rolling_sum += values[idx] - values[idx - window]
        result[idx] = rolling_sum / window
    return result


def _compute_rsi(values: List[float], period: int) -> List[Optional[float]]:
    if period <= 0:
        raise ValueError("RSI period must be > 0")
    result: List[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return result
    gains = 0.0
    losses = 0.0
    for idx in range(1, period + 1):
        change = values[idx] - values[idx - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period if losses else 0.0
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))
    for idx in range(period + 1, len(values)):
        change = values[idx] - values[idx - 1]
        gain = max(change, 0.0)
        loss = -min(change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        if avg_loss == 0:
            result[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[idx] = 100 - (100 / (1 + rs))
    return result


class MovingAverageCrossoverStrategy:
    """Simple MA golden cross / death cross strategy."""

    def __init__(self, short_window: int = 20, long_window: int = 50) -> None:
        if short_window >= long_window:
            raise ValueError("Short window must be smaller than long window.")
        self.short_window = short_window
        self.long_window = long_window

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Dict[str, Any]:
        candles, _, _ = _load_symbol_data(db_path, table_name)
        closes = [float(candle["close"]) for candle in candles]
        short_ma = _sma(closes, self.short_window)
        long_ma = _sma(closes, self.long_window)

        markers: List[Dict[str, Any]] = []
        trades: List[Dict[str, Any]] = []
        scan_candidates: List[Dict[str, Any]] = []
        open_trade: Optional[Dict[str, Any]] = None

        for idx in range(1, len(candles)):
            s_prev = short_ma[idx - 1]
            l_prev = long_ma[idx - 1]
            s_now = short_ma[idx]
            l_now = long_ma[idx]
            if s_prev is None or l_prev is None or s_now is None or l_now is None:
                continue
            candle = candles[idx]
            price = float(candle["close"])
            time_val = candle["time"]
            crossover = s_now > l_now and s_prev <= l_prev
            crossunder = s_now < l_now and s_prev >= l_prev
            if crossover:
                markers.append(
                    {
                        "id": f"ma_buy_{idx}",
                        "time": time_val,
                        "position": "belowBar",
                        "color": "#22c55e",
                        "shape": "arrowUp",
                        "text": f"BUY {price:.2f}",
                    }
                )
                open_trade = {
                    "entry_time": time_val,
                    "entry_price": price,
                    "entry_reason": "MA golden cross",
                }
                scan_candidates.append(
                    {
                        "date": time_val,
                        "price": price,
                        "score": round((s_now - l_now) / l_now, 4),
                        "note": "Golden cross",
                    }
                )
            elif crossunder and open_trade:
                markers.append(
                    {
                        "id": f"ma_sell_{idx}",
                        "time": time_val,
                        "position": "aboveBar",
                        "color": "#f87171",
                        "shape": "arrowDown",
                        "text": f"SELL {price:.2f}",
                    }
                )
                open_trade.update(
                    {
                        "exit_time": time_val,
                        "exit_price": price,
                        "exit_reason": "MA death cross",
                    }
                )
                trades.append(open_trade)
                open_trade = None
        status = f"Golden crosses: {sum(1 for m in markers if 'BUY' in m['text'])} · Death crosses: {sum(1 for m in markers if 'SELL' in m['text'])}"
        return {
            "strategy_name": "ma_crossover",
            "markers": markers,
            "status_message": status,
            "extra_data": {
                "trades": trades,
                "scan_candidates": scan_candidates[-50:],
            },
        }


class RSIMeanReversionStrategy:
    """RSI overbought/oversold mean-reversion strategy."""

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0) -> None:
        if oversold >= overbought:
            raise ValueError("Oversold must be below overbought.")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Dict[str, Any]:
        candles, _, _ = _load_symbol_data(db_path, table_name)
        closes = [float(candle["close"]) for candle in candles]
        rsi_series = _compute_rsi(closes, self.period)

        markers: List[Dict[str, Any]] = []
        trades: List[Dict[str, Any]] = []
        scan_candidates: List[Dict[str, Any]] = []
        open_trade: Optional[Dict[str, Any]] = None

        for idx in range(self.period + 1, len(candles)):
            rsi_value = rsi_series[idx]
            prev_rsi = rsi_series[idx - 1]
            if rsi_value is None or prev_rsi is None:
                continue
            candle = candles[idx]
            price = float(candle["close"])
            time_val = candle["time"]
            crossed_up = prev_rsi < self.oversold and rsi_value >= self.oversold
            crossed_down = prev_rsi > self.overbought and rsi_value <= self.overbought
            if crossed_up:
                markers.append(
                    {
                        "id": f"rsi_buy_{idx}",
                        "time": time_val,
                        "position": "belowBar",
                        "color": "#10b981",
                        "shape": "circle",
                        "text": f"RSI BUY {rsi_value:.1f}",
                    }
                )
                open_trade = {
                    "entry_time": time_val,
                    "entry_price": price,
                    "entry_reason": "RSI exits oversold",
                }
                scan_candidates.append(
                    {
                        "date": time_val,
                        "price": price,
                        "score": round(1 - rsi_value / 100.0, 4),
                        "note": "RSI buy",
                    }
                )
            elif crossed_down and open_trade:
                markers.append(
                    {
                        "id": f"rsi_sell_{idx}",
                        "time": time_val,
                        "position": "aboveBar",
                        "color": "#f97316",
                        "shape": "circle",
                        "text": f"RSI SELL {rsi_value:.1f}",
                    }
                )
                open_trade.update(
                    {
                        "exit_time": time_val,
                        "exit_price": price,
                        "exit_reason": "RSI falls from overbought",
                    }
                )
                trades.append(open_trade)
                open_trade = None
        status = f"RSI buys: {sum(1 for m in markers if 'BUY' in m['text'])} · sells: {sum(1 for m in markers if 'SELL' in m['text'])}"
        return {
            "strategy_name": "rsi_reversion",
            "markers": markers,
            "status_message": status,
            "extra_data": {
                "trades": trades,
                "scan_candidates": scan_candidates[-50:],
            },
        }


class DonchianBreakoutStrategy:
    """Donchian channel breakout strategy."""

    def __init__(self, lookback: int = 20) -> None:
        if lookback < 5:
            raise ValueError("Lookback must be >= 5")
        self.lookback = lookback

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Dict[str, Any]:
        candles, _, _ = _load_symbol_data(db_path, table_name)
        markers: List[Dict[str, Any]] = []
        trades: List[Dict[str, Any]] = []
        scan_candidates: List[Dict[str, Any]] = []
        open_trade: Optional[Dict[str, Any]] = None

        for idx in range(self.lookback, len(candles)):
            window = candles[idx - self.lookback : idx]
            upper = max(float(item["high"]) for item in window)
            lower = min(float(item["low"]) for item in window)
            candle = candles[idx]
            close_price = float(candle["close"])
            time_val = candle["time"]
            if open_trade is None and close_price > upper:
                markers.append(
                    {
                        "id": f"brk_buy_{idx}",
                        "time": time_val,
                        "position": "belowBar",
                        "color": "#16a34a",
                        "shape": "pin",
                        "text": f"Breakout BUY {close_price:.2f}",
                    }
                )
                open_trade = {
                    "entry_time": time_val,
                    "entry_price": close_price,
                    "entry_reason": "Upper band breakout",
                }
                scan_candidates.append(
                    {
                        "date": time_val,
                        "price": close_price,
                        "score": 1.0,
                        "note": "Breakout long",
                    }
                )
            elif open_trade and close_price < lower:
                markers.append(
                    {
                        "id": f"brk_sell_{idx}",
                        "time": time_val,
                        "position": "aboveBar",
                        "color": "#dc2626",
                        "shape": "pin",
                        "text": f"Breakout SELL {close_price:.2f}",
                    }
                )
                open_trade.update(
                    {
                        "exit_time": time_val,
                        "exit_price": close_price,
                        "exit_reason": "Lower band exit",
                    }
                )
                trades.append(open_trade)
                open_trade = None
        status = f"Breakout signals: {sum(1 for m in markers if 'BUY' in m['text'])}"
        return {
            "strategy_name": "donchian_breakout",
            "markers": markers,
            "status_message": status,
            "extra_data": {
                "trades": trades,
                "scan_candidates": scan_candidates[-50:],
            },
        }


def run_ma_workbench(context: "StrategyContext") -> "StrategyRunResult":
    if StrategyContext is None or StrategyRunResult is None:
        raise RuntimeError("Strategy runtime not available.")
    params = context.params or {}

    def _get_int(key: str, default: int) -> int:
        try:
            return int(float(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    short_window = max(3, _get_int("short_window", 20))
    long_window = max(short_window + 1, _get_int("long_window", 50))

    strategy = MovingAverageCrossoverStrategy(short_window=short_window, long_window=long_window)
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result("ma_crossover", raw_result)


def run_rsi_workbench(context: "StrategyContext") -> "StrategyRunResult":
    if StrategyContext is None or StrategyRunResult is None:
        raise RuntimeError("Strategy runtime not available.")
    params = context.params or {}

    def _get_int(key: str, default: int) -> int:
        try:
            return int(float(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _get_float(key: str, default: float) -> float:
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            return default

    period = max(2, _get_int("period", 14))
    oversold = max(0.0, min(_get_float("oversold", 30.0), 99.0))
    overbought = max(oversold + 1.0, min(_get_float("overbought", 70.0), 100.0))

    strategy = RSIMeanReversionStrategy(period=period, oversold=oversold, overbought=overbought)
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result("rsi_reversion", raw_result)


def run_donchian_workbench(context: "StrategyContext") -> "StrategyRunResult":
    if StrategyContext is None or StrategyRunResult is None:
        raise RuntimeError("Strategy runtime not available.")
    params = context.params or {}

    def _get_int(key: str, default: int) -> int:
        try:
            return int(float(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    lookback = max(5, _get_int("lookback", 20))

    strategy = DonchianBreakoutStrategy(lookback=lookback)
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result("donchian_breakout", raw_result)


__all__ = [
    "MovingAverageCrossoverStrategy",
    "RSIMeanReversionStrategy",
    "DonchianBreakoutStrategy",
    "PARAMETERS_BY_STRATEGY",
    "run_ma_workbench",
    "run_rsi_workbench",
    "run_donchian_workbench",
]
