from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

DEFAULT_SAMPLE_SYMBOLS: Sequence[Dict[str, Any]] = (
    {
        "symbol": "300122",
        "name": "智飞生物",
        "last_price": 20.10,
        "change_percent": 0.70,
        "display": "智飞生物 300122",
        "table": "sample_300122",
    },
    {
        "symbol": "300059",
        "name": "东方财富",
        "last_price": 15.19,
        "change_percent": 4.47,
        "display": "东方财富 300059",
        "table": "sample_300059",
    },
    {
        "symbol": "603986",
        "name": "兆易创新",
        "last_price": 340.80,
        "change_percent": -0.85,
        "display": "兆易创新 603986",
        "table": "sample_603986",
    },
    {
        "symbol": "600519",
        "name": "贵州茅台",
        "last_price": 1680.00,
        "change_percent": -1.12,
        "display": "贵州茅台 600519",
        "table": "sample_600519",
    },
)


def load_sample_symbols(*, source: str | Path | None = None) -> List[Dict[str, Any]]:
    """Load sample symbol entries from ``source`` or fall back to defaults."""

    if source is not None:
        path = Path(source)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return _normalize_entries(payload)
        except Exception:
            pass
    return [dict(entry) for entry in DEFAULT_SAMPLE_SYMBOLS]


def _normalize_entries(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        candidates: Iterable[Any] = payload.values()
    elif isinstance(payload, list):
        candidates = payload
    else:
        return [dict(entry) for entry in DEFAULT_SAMPLE_SYMBOLS]

    normalized: List[Dict[str, Any]] = []
    for entry in candidates:
        if isinstance(entry, dict):
            normalized.append(dict(entry))
    return normalized or [dict(entry) for entry in DEFAULT_SAMPLE_SYMBOLS]
