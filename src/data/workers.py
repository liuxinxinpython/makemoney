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
    from .tushare_sync import sync_tushare_daily, sync_tushare_daily_by_date, SyncStats  # type: ignore
    HAS_TUSHARE_SYNC = True
except Exception:
    sync_tushare_daily = None  # type: ignore
    sync_tushare_daily_by_date = None  # type: ignore
    SyncStats = object  # type: ignore
    HAS_TUSHARE_SYNC = False

try:
    import tushare as ts  # type: ignore
    HAS_TUSHARE = True
except Exception:
    ts = None  # type: ignore
    HAS_TUSHARE = False

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


class TushareSyncWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(str)
    progress_count = QtCore.pyqtSignal(int, int)
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        db_path: Path,
        token: str,
        *,
        tables: Optional[List[str]] = None,
        lookback_days: int = 730,
        mode: str = "by_date",  # by_date | by_symbol
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.token = token
        self.tables = tables
        self.lookback_days = lookback_days
        self.mode = mode
        self.start_date = start_date
        self.end_date = end_date

    @QtCore.pyqtSlot()
    def run(self) -> None:
        if not HAS_TUSHARE_SYNC or sync_tushare_daily is None:
            self.failed.emit("未找到 tushare_sync 或未安装 tushare 库")
            return
        if not HAS_TUSHARE or ts is None:
            self.failed.emit("未安装 tushare 库")
            return
        try:
            if not self.token:
                self.failed.emit("缺少 Tushare Token")
                return
            # 预检 daily 权限，避免长任务才发现 108
            try:
                pro = ts.pro_api(self.token)
                pro.daily(limit=1)
            except Exception as exc:
                self.failed.emit(f"预检 daily 接口失败: {exc}")
                return

            if self.mode == "by_date" and sync_tushare_daily_by_date is not None:
                table_names = self.tables
                if table_names is None:
                    try:
                        with sqlite3.connect(self.db_path) as conn:
                            rows = conn.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                            ).fetchall()
                            table_names = [r[0] for r in rows]
                    except Exception:
                        table_names = None
                stats: SyncStats = sync_tushare_daily_by_date(
                    db_path=self.db_path,
                    token=self.token,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    lookback_days=self.lookback_days,
                    tables_hint=table_names,
                    progress=self.progress.emit,
                    progress_count=self.progress_count.emit,
                    use_trade_cal=False,
                )
            else:
                stats = sync_tushare_daily(
                    db_path=self.db_path,
                    token=self.token,
                    tables=self.tables,
                    lookback_days=self.lookback_days,
                    progress=self.progress.emit,
                )
            self.finished.emit(stats)
        except Exception as exc:  # pragma: no cover - runtime failure feedback
            self.failed.emit(str(exc))


class TushareTestWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self) -> None:
        if not HAS_TUSHARE or ts is None:
            self.failed.emit("未安装 tushare 库")
            return
        try:
            pro = ts.pro_api(self.token)
            # 尽量贴近官方示例：直接调 daily，取 5 条
            df = pro.daily(limit=5, fields=[
                "ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"
            ])
            rows = len(df)
            first_code = df["ts_code"].iloc[0] if rows else "无数据"
            self.finished.emit(f"连通成功：返回 {rows} 行，示例 {first_code}")
        except Exception as exc:  # pragma: no cover
            self.failed.emit(f"连通失败: {exc}")


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
            def fetch_latest_identity(
                connection: sqlite3.Connection,
                escaped_name: str,
            ) -> Optional[Tuple[Any, Any, Any, Any, Any]]:
                """Fetch basic identity plus last price/change metadata."""

                queries: Tuple[Tuple[str, str], ...] = (
                    ("symbol, name, close, chg_pct, prev_close", "rowid"),
                    ("symbol, name, close, chg_pct, prev_close", "date"),
                    ("symbol, name", "rowid"),
                    ("symbol, name", "date"),
                )

                for columns, order_key in queries:
                    query = (
                        f'SELECT {columns} FROM "{escaped_name}" '
                        f"ORDER BY {order_key} DESC LIMIT 1"
                    )
                    try:
                        row = connection.execute(query).fetchone()
                    except Exception:
                        continue
                    if not row:
                        continue
                    values = list(row)
                    while len(values) < 5:
                        values.append(None)
                    return tuple(values[:5])
                return None

            entries: List[Dict[str, Any]] = []
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
                    sym = str(table_name).upper()
                    name = ""
                    last_price: Optional[float] = None
                    change_percent: Optional[float] = None
                    try:
                        latest = fetch_latest_identity(conn, escaped)
                        if latest:
                            latest_symbol, latest_name, raw_price, raw_change, raw_prev_close = latest
                            if latest_symbol:
                                sym = str(latest_symbol).strip().upper()
                            if latest_name:
                                name = str(latest_name).strip()
                            last_price = _safe_float(raw_price)
                            change_percent = _safe_float(raw_change)
                            if change_percent is None:
                                prev_close = _safe_float(raw_prev_close)
                                if (
                                    prev_close is not None
                                    and prev_close != 0
                                    and last_price is not None
                                ):
                                    change_percent = ((last_price - prev_close) / prev_close) * 100
                    except Exception:
                        pass

                    entry: Dict[str, Any] = {
                        "table": str(table_name),
                        "symbol": sym,
                        "name": name,
                        "display": f"{sym} · {name}" if name else sym,
                        "last_price": last_price,
                        "change_percent": change_percent,
                    }
                    entries.append(entry)
                
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
