from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

try:
    from ..displays import DisplayResult  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    DisplayResult = None

from ..research import StrategyRunResult


def serialize_run_result(strategy_name: str, raw_result: Any) -> StrategyRunResult:
    """将策略的原始运行结果统一转换为 StrategyRunResult。"""
    markers: List[Dict[str, Any]] = []
    overlays: List[Dict[str, Any]] = []
    status_message: Optional[str] = None
    extra_data: Dict[str, Any] = {}

    if raw_result is None:
        pass
    elif DisplayResult is not None and isinstance(raw_result, DisplayResult):
        markers = list(getattr(raw_result, "markers", []) or [])
        overlays = list(getattr(raw_result, "overlays", []) or [])
        status_message = getattr(raw_result, "status_message", None)
        extra_data = dict(getattr(raw_result, "extra_data", {}) or {})
    else:
        markers = list(raw_result.get("markers", []) or [])  # type: ignore[union-attr]
        overlays = list(raw_result.get("overlays", []) or [])  # type: ignore[union-attr]
        status_message = raw_result.get("status_message")  # type: ignore[union-attr]
        extra_data = dict(raw_result.get("extra_data", {}) or {})  # type: ignore[union-attr]

    return StrategyRunResult(
        strategy_name=strategy_name,
        markers=markers,
        overlays=overlays,
        status_message=status_message,
        extra_data=extra_data,
    )


def augment_markers_with_trade_signals(
    markers: List[Dict[str, Any]],
    extra_data: Optional[Dict[str, Any]],
    *,
    strategy_key: str,
) -> List[Dict[str, Any]]:
    """附加交易进出场标记, 用于 ECharts 预览等场景。"""
    trades = list((extra_data or {}).get("trades", []) or [])
    if not trades:
        return markers

    enriched = list(markers)
    buy_times: Set[Any] = {
        m.get("time")
        for m in markers
        if isinstance(m.get("text"), str) and "BUY" in m["text"].upper()
    }
    sell_times: Set[Any] = {
        m.get("time")
        for m in markers
        if isinstance(m.get("text"), str) and "SELL" in m["text"].upper()
    }

    for idx, trade in enumerate(trades):
        entry_time = trade.get("entry_time") or trade.get("entryTime")
        entry_price = _safe_float(trade.get("entry_price") or trade.get("entryPrice"))
        entry_label = trade.get("entry_reason") or trade.get("entryReason")
        if entry_time and entry_time not in buy_times:
            text = entry_label or (f"BUY {entry_price:.2f}" if entry_price is not None else "BUY")
            enriched.append(
                {
                    "id": f"{strategy_key}_buy_{idx}",
                    "time": entry_time,
                    "position": "belowBar",
                    "color": "#22c55e",
                    "shape": "triangle",
                    "text": text,
                }
            )
            buy_times.add(entry_time)

        exit_time = trade.get("exit_time") or trade.get("exitTime")
        exit_price = _safe_float(trade.get("exit_price") or trade.get("exitPrice"))
        exit_label = trade.get("exit_reason") or trade.get("exitReason")
        if exit_time and exit_time not in sell_times:
            text = exit_label or (f"SELL {exit_price:.2f}" if exit_price is not None else "SELL")
            enriched.append(
                {
                    "id": f"{strategy_key}_sell_{idx}",
                    "time": exit_time,
                    "position": "aboveBar",
                    "color": "#f87171",
                    "shape": "triangle",
                    "text": text,
                }
            )
            sell_times.add(exit_time)
    return enriched


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["serialize_run_result", "augment_markers_with_trade_signals"]
