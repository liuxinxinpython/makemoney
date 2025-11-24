"""Volume-price pattern scanner for A-share daily SQLite database.

This module looks for symbols that exhibit a consolidation, breakout,
retest, and renewed-volume pattern reminiscent of classic price/volume
setups. It aims to provide an extendable foundation for custom stock
selection logic that can be integrated with the existing PyQt front-end.
"""

from __future__ import annotations

import argparse
import dataclasses
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


@dataclasses.dataclass
class RangeSegment:
    kind: str
    start_index: int
    end_index: int
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    high: float
    low: float
    strength: float

    def to_overlay_payload(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "start": self.start_date.strftime("%Y-%m-%d"),
            "end": self.end_date.strftime("%Y-%m-%d"),
            "top": round(float(self.high), 4),
            "bottom": round(float(self.low), 4),
            "strength": float(self.strength),
        }


@dataclasses.dataclass
class PatternMatch:
    """Represents a detected volume-price pattern for a single symbol."""

    table: str
    symbol: str
    name: str
    consolidation_start: pd.Timestamp
    consolidation_end: pd.Timestamp
    breakout_date: pd.Timestamp
    retest_date: pd.Timestamp
    mini_breakout_date: pd.Timestamp
    mini_pullback_date: pd.Timestamp
    reconfirm_date: pd.Timestamp
    consolidation_range_pct: float
    breakout_volume_ratio: float
    reconfirm_volume_ratio: float

    def to_summary(self) -> Dict[str, str]:
        return {
            "table": self.table,
            "symbol": self.symbol,
            "name": self.name,
            "consolidation": f"{self.consolidation_start.date()} ~ {self.consolidation_end.date()}",
            "breakout": str(self.breakout_date.date()),
            "retest": str(self.retest_date.date()),
            "mini_breakout": str(self.mini_breakout_date.date()),
            "mini_pullback": str(self.mini_pullback_date.date()),
            "reconfirm": str(self.reconfirm_date.date()),
            "range_pct": f"{self.consolidation_range_pct:.2f}%",
            "breakout_vol": f"{self.breakout_volume_ratio:.2f}x",
            "reconfirm_vol": f"{self.reconfirm_volume_ratio:.2f}x",
        }

    def to_summary(self) -> Dict[str, str]:
        return {
            "table": self.table,
            "symbol": self.symbol,
            "name": self.name,
            "consolidation": f"{self.consolidation_start.date()} ~ {self.consolidation_end.date()}",
            "breakout": str(self.breakout_date.date()),
            "retest": str(self.retest_date.date()),
            "mini_breakout": str(self.mini_breakout_date.date()),
            "mini_pullback": str(self.mini_pullback_date.date()),
            "reconfirm": str(self.reconfirm_date.date()),
            "range_pct": f"{self.consolidation_range_pct:.2f}%",
            "breakout_vol": f"{self.breakout_volume_ratio:.2f}x",
            "reconfirm_vol": f"{self.reconfirm_volume_ratio:.2f}x",
        }


@dataclasses.dataclass
class ScanConfig:
    lookback_days: int = 420
    consolidation_days: int = 30
    long_consolidation_days: int = 45
    consolidation_band_pct: float = 6.0
    breakout_buffer_pct: float = 2.5
    breakout_volume_ratio: float = 1.8
    post_breakout_min_gap: int = 35
    retest_window: int = 60
    retest_margin_pct: float = 2.5
    mini_cycle_window: int = 30
    mini_breakout_buffer_pct: float = 3.0
    mini_pullback_window: int = 15
    reconfirm_window: int = 25
    reconfirm_volume_ratio: float = 2.0
    reconfirm_close_buffer_pct: float = 2.0

    def consolidation_band_ratio(self) -> float:
        return self.consolidation_band_pct / 100.0

    def breakout_buffer_ratio(self) -> float:
        return self.breakout_buffer_pct / 100.0

    def retest_margin_ratio(self) -> float:
        return self.retest_margin_pct / 100.0

    def reconfirm_close_buffer_ratio(self) -> float:
        return self.reconfirm_close_buffer_pct / 100.0

    def mini_breakout_buffer_ratio(self) -> float:
        return self.mini_breakout_buffer_pct / 100.0


def iter_symbol_tables(conn: sqlite3.Connection) -> Iterable[str]:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for (table_name,) in cursor.fetchall():
        yield str(table_name)


def load_price_frame(conn: sqlite3.Connection, table: str, lookback_days: int) -> Optional[pd.DataFrame]:
    escaped = table.replace("\"", "\"\"")
    if lookback_days > 0:
        query = (
            "SELECT date, open, high, low, close, volume, name, symbol "
            f"FROM \"{escaped}\" ORDER BY date DESC LIMIT {lookback_days}"
        )
    else:
        # Load all data when lookback_days is 0 or negative
        query = (
            "SELECT date, open, high, low, close, volume, name, symbol "
            f"FROM \"{escaped}\" ORDER BY date"
        )
    df = pd.read_sql_query(query, conn)
    if df.empty:
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        return None
    return df
