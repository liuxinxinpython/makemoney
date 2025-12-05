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
    from .data_loader import load_candles_from_sqlite
except Exception:
    load_candles_from_sqlite = None


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
            if load_candles_from_sqlite is None:
                raise RuntimeError("缺少 load_candles_from_sqlite 函数")
            max_rows = self.lookback_days if self.lookback_days > 0 else None
            payload = load_candles_from_sqlite(self.db_path, self.table, max_rows=max_rows)
            self.finished.emit(payload)
        except Exception as exc:
            self.failed.emit(str(exc))
