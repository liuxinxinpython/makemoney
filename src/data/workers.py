from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt5 import QtCore  # type: ignore[import-not-found]

try:
    from .import_excel_to_sqlite import import_directory
    HAS_IMPORTER = True
except Exception:
    HAS_IMPORTER = False

try:
    from .volume_price_selector import load_price_frame
except Exception:
    load_price_frame = None


class ImportWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, excel_dir: Path, db_path: Path, replace: bool) -> None:
        super().__init__()
        self.excel_dir = excel_dir
        self.db_path = db_path
        self.replace = replace

    @QtCore.pyqtSlot()
    def run(self) -> None:
        if not HAS_IMPORTER:
            self.failed.emit("未找到导入脚本 import_excel_to_sqlite.py")
            return

        try:
            tables = import_directory(
                self.excel_dir,
                self.db_path,
                replace=self.replace,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(tables)
        except Exception as exc:  # pragma: no cover - runtime failure feedback
            self.failed.emit(str(exc))


class SymbolLoadWorker(QtCore.QObject):
    """Background worker to enumerate tables and fetch last-symbol metadata from each table.

    This avoids blocking the UI loop while a large SQLite database is being read.
    """
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            entries: List[Dict[str, str]] = []
            # We open a fresh connection on this worker thread -- sqlite is allowed to be read concurrently.
            path_uri = Path(self.db_path).resolve().as_uri()
            conn = sqlite3.connect(f'{path_uri}?mode=ro', uri=True, check_same_thread=False)
            try:
                # Use a smaller cache for fast metadata queries during enumeration.
                try:
                    conn.execute('PRAGMA cache_size = -2000')
                except Exception:
                    pass

                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                rows = cursor.fetchall()
                total_tables = len(rows)
                
                self.progress.emit(f"正在扫描数据库，共 {total_tables} 个股票...")
                
                for i, (table_name,) in enumerate(rows):
                    if not table_name:
                        continue
                    
                    # 发送进度更新
                    if (i + 1) % 100 == 0 or i == 0:  # 每100个或第一个发送一次进度
                        self.progress.emit(f"正在加载股票信息... ({i + 1}/{total_tables})")
                    
                    escaped = str(table_name).replace('"', '""')
                    try:
                        meta = conn.execute(f'SELECT symbol, name FROM "{escaped}" ORDER BY date DESC LIMIT 1')
                        meta_row = meta.fetchone()
                        if meta_row:
                            sym = meta_row[0] if meta_row[0] is not None else str(table_name).upper()
                            name = meta_row[1] if meta_row[1] is not None else ""
                        else:
                            sym = str(table_name).upper()
                            name = ""
                    except Exception:
                        sym = str(table_name).upper()
                        name = ""
                    entries.append({"table": str(table_name), "symbol": sym, "name": name, "display": f"{sym} · {name}" if name else sym})
                
                self.progress.emit(f"股票列表加载完成，共 {len(entries)} 个股票")
                self.finished.emit(entries)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as exc:  # pragma: no cover - runtime failure feedback
            self.failed.emit(str(exc))


class CandleLoadWorker(QtCore.QObject):
    """Background worker to load candle and volume data for a given table."""
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, db_path: Path, table: str, lookback_days: int = 0) -> None:
        super().__init__()
        self.db_path = db_path
        self.table = table
        self.lookback_days = lookback_days

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            # Use pandas loader to read limited rows for the table
            path_uri = Path(self.db_path).resolve().as_uri()
            conn = sqlite3.connect(f'{path_uri}?mode=ro', uri=True, check_same_thread=False)
            try:
                if load_price_frame is None:
                    self.failed.emit("缺少 volume_price_selector.load_price_frame 函数")
                    return
                df = load_price_frame(conn, self.table, self.lookback_days)
                if df is None or df.empty:
                    self.finished.emit(None)
                    return
                candles: List[Dict[str, Any]] = []
                volumes: List[Dict[str, Any]] = []
                instrument: Dict[str, str] = {"symbol": str(self.table).upper(), "name": ""}
                for _, row in df.iterrows():
                    ts = row["date"]
                    if hasattr(ts, 'strftime'):
                        date_str = ts.strftime('%Y-%m-%d')
                    else:
                        date_str = str(ts)
                    open_ = float(row["open"])
                    high = float(row["high"])
                    low = float(row["low"])
                    close = float(row["close"])
                    candles.append({"time": date_str, "open": open_, "high": high, "low": low, "close": close})
                    volumes.append({"time": date_str, "value": float(row.get("volume", 0.0)), "color": "#f03752" if close >= open_ else "#13b355"})
                try:
                    name = str(df["name"].iloc[-1]) if "name" in df.columns else ""
                    symbol = str(df["symbol"].iloc[-1]) if "symbol" in df.columns else str(self.table).upper()
                    instrument = {"symbol": symbol, "name": name}
                except Exception:
                    pass
                self.finished.emit((candles, volumes, instrument))
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as exc:
            self.failed.emit(str(exc))
