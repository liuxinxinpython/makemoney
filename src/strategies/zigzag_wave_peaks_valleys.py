from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

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
            label="Min reversal (%)",
            type="number",
            default=5.0,
            description="Price must reverse at least this percent to confirm a new pivot.",
        ),
        StrategyParameter(
            key="max_pivots",
            label="Max pivots",
            type="number",
            default=80,
            description="Limit the number of pivots/markers returned to avoid over-plotting.",
        ),
    ]


class ZigZagWavePeaksValleysStrategy:
    """
    A small ZigZag-style detector: finds swing highs/lows on closes with a minimum reversal
    threshold, and marks valleys as BUY and peaks as SELL for preview charts.
    """

    def __init__(self, min_reversal_pct: float = 5.0, max_pivots: int = 80) -> None:
        if not HAS_DATA_LOADER:
            raise ImportError("Missing data_loader module; cannot load candles.")
        # Convert percent to fraction; enforce a tiny floor to avoid division by zero.
        self.min_reversal = max(0.0005, float(min_reversal_pct) / 100.0)
        self.max_pivots = max(1, int(max_pivots))

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional[Any]:
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f"Unable to load candles for symbol {table_name}")
        candles, _volumes, _instrument = data

        pivots = self._detect_pivots(candles, self.min_reversal)
        if len(pivots) > self.max_pivots:
            pivots = pivots[-self.max_pivots :]  # keep the most recent swings
        # Fallback so preview always shows at least one buy/sell pair.
        if not pivots and candles:
            pivots = [
                {"index": 0, "type": "valley"},
                {"index": len(candles) - 1, "type": "peak"},
            ]

        markers = self._pivot_markers(pivots, candles)
        overlays: List[Dict[str, Any]] = []  # nothing fancy for preview
        status_message = f"Markers {len(markers)}, pivots {len(pivots)}"
        extra_data: Dict[str, Any] = {"pivots": pivots}

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

    @staticmethod
    def _detect_pivots(candles: List[Dict[str, Any]], min_reversal: float) -> List[Dict[str, Any]]:
        """Very small ZigZag on close prices using a percent reversal threshold."""
        if len(candles) < 3:
            return []

        prices = [float(c.get("close", 0) or 0) for c in candles]
        pivots: List[Dict[str, Any]] = []
        trend = 0  # 0 undecided, 1 up, -1 down
        last_pivot_idx = 0
        last_pivot_price = prices[0]

        for idx in range(1, len(prices)):
            price = prices[idx]
            if trend == 0:
                change = (price - last_pivot_price) / last_pivot_price if last_pivot_price else 0.0
                if change >= min_reversal:
                    trend = 1
                    pivots.append({"index": last_pivot_idx, "type": "valley"})
                    last_pivot_idx = idx
                    last_pivot_price = price
                elif change <= -min_reversal:
                    trend = -1
                    pivots.append({"index": last_pivot_idx, "type": "peak"})
                    last_pivot_idx = idx
                    last_pivot_price = price
            elif trend == 1:
                # in an up trend; keep tracking highs until a reversal beyond threshold
                if price > last_pivot_price:
                    last_pivot_idx = idx
                    last_pivot_price = price
                else:
                    change = (last_pivot_price - price) / last_pivot_price if last_pivot_price else 0.0
                    if change >= min_reversal:
                        pivots.append({"index": last_pivot_idx, "type": "peak"})
                        trend = -1
                        last_pivot_idx = idx
                        last_pivot_price = price
            else:  # trend == -1
                # in a down trend; keep tracking lows until a reversal beyond threshold
                if price < last_pivot_price:
                    last_pivot_idx = idx
                    last_pivot_price = price
                else:
                    change = (price - last_pivot_price) / last_pivot_price if last_pivot_price else 0.0
                    if change >= min_reversal:
                        pivots.append({"index": last_pivot_idx, "type": "valley"})
                        trend = 1
                        last_pivot_idx = idx
                        last_pivot_price = price

        # Ensure the last bar is marked as the opposite pivot so the stroke is closed.
        if pivots and pivots[-1]["index"] != len(candles) - 1:
            last_type = pivots[-1]["type"]
            pivots.append({"index": len(candles) - 1, "type": "peak" if last_type == "valley" else "valley"})
        return pivots

    @staticmethod
    def _pivot_markers(pivots: List[Dict[str, Any]], candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        markers: List[Dict[str, Any]] = []
        for idx, pivot in enumerate(pivots):
            c = candles[pivot["index"]]
            is_valley = pivot["type"] == "valley"
            price = float(c.get("close", 0) or 0)
            markers.append(
                {
                    "id": f"zigzag_pivot_{idx}",
                    "time": c.get("time"),
                    "position": "belowBar" if is_valley else "aboveBar",
                    "color": "#22c55e" if is_valley else "#ef4444",
                    "shape": "arrowUp" if is_valley else "arrowDown",
                    "text": f"{'BUY' if is_valley else 'SELL'} {price:.2f}",
                    "price": price,
                }
            )
        return markers


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
    max_pivots = _get_int("max_pivots", 80)

    strategy = ZigZagWavePeaksValleysStrategy(
        min_reversal_pct=min_reversal_pct,
        max_pivots=max_pivots,
    )
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result("zigzag_wave_peaks_valleys", raw_result)


__all__ = ["ZigZagWavePeaksValleysStrategy", "ZIGZAG_STRATEGY_PARAMETERS", "run_zigzag_workbench"]
