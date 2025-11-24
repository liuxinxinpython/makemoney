"""
数据加载器模块
包含从数据库加载K线数据的功能
"""

import sqlite3
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

try:
    import pandas as pd  # type: ignore[import-not-found]
    HAS_PANDAS = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_PANDAS = False
    pd = None  # type: ignore[assignment]


def load_candles_from_sqlite(
    db_path: Path,
    table_name: str,
) -> Optional[Tuple[List[Dict[str, float]], List[Dict[str, float]], Dict[str, str]]]:
    """
    从SQLite数据库加载K线数据

    Args:
        db_path: 数据库文件路径
        table_name: 表名

    Returns:
        (candles, volumes, instrument) 或 None
    """
    if not HAS_PANDAS:
        return None

    if not db_path.exists():
        return None

    escaped_table = table_name.replace("\"", "\"\"")
    query = (
        "SELECT date, open, high, low, close, volume, name, symbol FROM "
        f'"{escaped_table}" ORDER BY date'
    )

    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(query, conn)
    except Exception:
        return None

    if df.empty:
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return None

    candles: List[Dict[str, float]] = []
    volumes: List[Dict[str, float]] = []
    instrument_name: Optional[str] = None
    instrument_symbol: Optional[str] = None

    for _, row in df.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        open_ = float(row["open"]) if not pd.isna(row["open"]) else None
        high = float(row["high"]) if not pd.isna(row["high"]) else None
        low = float(row["low"]) if not pd.isna(row["low"]) else None
        close = float(row["close"]) if not pd.isna(row["close"]) else None
        if None in (open_, high, low, close):
            continue

        volume_raw = row.get("volume")
        volume_value = float(volume_raw) if volume_raw is not None and not pd.isna(volume_raw) else 0.0
        volume_wan = round(volume_value / 1e4, 2)

        if instrument_name is None and "name" in df.columns:
            name_value = row.get("name")
            if name_value is not None and not pd.isna(name_value):
                instrument_name = str(name_value).strip()
        if instrument_symbol is None and "symbol" in df.columns:
            symbol_value = row.get("symbol")
            if symbol_value is not None and not pd.isna(symbol_value):
                instrument_symbol = str(symbol_value).strip().upper()

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
                "value": volume_wan,
                "color": "#f03752" if close >= open_ else "#13b355",
            }
        )

    if not candles:
        return None

    instrument = {
        "symbol": instrument_symbol or table_name.upper(),
        "name": instrument_name or "",
    }

    return candles, volumes, instrument