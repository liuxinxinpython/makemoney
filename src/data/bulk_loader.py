from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Any

try:
    import pandas as pd  # type: ignore[import-not-found]
    HAS_PANDAS = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_PANDAS = False
    pd = None  # type: ignore[assignment]

CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "name", "symbol"]

BulkPayload = Tuple[List[Dict[str, float]], List[Dict[str, float]], Dict[str, str]]


def _apply_fast_pragmas(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=OFF;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-200000;")  # ~200MB page cache
    except Exception:
        pass


def load_candles_bulk(
    db_path: Path,
    table_names: Iterable[str],
    *,
    limit_per_table: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, BulkPayload]:
    """Load multiple tables in a single pandas call to reduce SQLite round-trips."""
    tables = [name for name in table_names if name]
    if not tables or not HAS_PANDAS:
        return {}

    subqueries: List[str] = []
    for idx, table in enumerate(tables):
        escaped = table.replace('"', '""')
        where_clause = _build_where_clause(start_date, end_date)
        base = (
            f'SELECT "{escaped}" AS __table, date, open, high, low, close, volume, name, symbol '
            f'FROM "{escaped}"{where_clause}'
        )
        if limit_per_table and limit_per_table > 0:
            base = f"SELECT * FROM ({base} ORDER BY date DESC LIMIT {int(limit_per_table)}) AS limited_{idx}"
        subqueries.append(base)

    if not subqueries:
        return {}

    union_sql = " UNION ALL ".join(subqueries)
    try:
        with sqlite3.connect(db_path) as conn:
            _apply_fast_pragmas(conn)
            frame = pd.read_sql_query(union_sql, conn)
    except Exception:
        return {}

    if frame.empty:
        return {}

    grouped = frame.groupby("__table")
    payloads: Dict[str, BulkPayload] = {}
    for table, group in grouped:
        payload = _frame_to_payload(str(table), group)
        if payload[0]:  # at least one candle
            payloads[str(table)] = payload
    return payloads


def _frame_to_payload(table_name: str, frame: "pd.DataFrame") -> BulkPayload:
    candles: List[Dict[str, float]] = []
    volumes: List[Dict[str, float]] = []
    instrument_name: Optional[str] = None
    instrument_symbol: Optional[str] = None

    frame_sorted = frame.sort_values("date")
    for _, row in frame_sorted.iterrows():
        date_value = row.get("date")
        if pd.isna(date_value):
            continue
        if hasattr(date_value, "strftime"):
            date_str = date_value.strftime("%Y-%m-%d")
        else:
            date_str = str(date_value)[:10]
        open_ = _safe_float(row.get("open"))
        high = _safe_float(row.get("high"))
        low = _safe_float(row.get("low"))
        close = _safe_float(row.get("close"))
        if None in (open_, high, low, close):
            continue
        volume_raw = _safe_float(row.get("volume")) or 0.0
        if instrument_name is None and isinstance(row.get("name"), str):
            instrument_name = row.get("name").strip()
        symbol_cell = row.get("symbol")
        if instrument_symbol is None and isinstance(symbol_cell, str):
            instrument_symbol = symbol_cell.strip().upper()
        candles.append(
            {
                "time": date_str,
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
            }
        )
        volumes.append(
            {
                "time": date_str,
                "value": round(volume_raw / 1e4, 2),
                "color": "#f03752" if close >= open_ else "#13b355",
            }
        )

    instrument = {
        "symbol": instrument_symbol or table_name.upper(),
        "name": instrument_name or "",
    }
    return candles, volumes, instrument


def _build_where_clause(start_date: Optional[date], end_date: Optional[date]) -> str:
    clauses: List[str] = []
    if start_date:
        clauses.append(f"date >= '{start_date:%Y-%m-%d}'")
    if end_date:
        clauses.append(f"date <= '{end_date:%Y-%m-%d}'")
    if not clauses:
        return ""
    return " WHERE " + " AND ".join(clauses)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["load_candles_bulk", "BulkPayload"]
