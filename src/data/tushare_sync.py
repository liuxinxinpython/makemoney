from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:
    import tushare as ts  # type: ignore
except Exception as exc:  # pragma: no cover - optional dependency
    ts = None
    _TS_IMPORT_ERROR = exc
else:
    _TS_IMPORT_ERROR = None

# Default schema aligns with import_excel_to_sqlite output.
DEFAULT_COLUMNS: Tuple[str, ...] = (
    "symbol",
    "name",
    "industry",
    "region",
    "list_date",
    "ts_code",
    "date",
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "chg_amount",
    "chg_pct",
    "volume_hand",
    "volume",
    "turnover_k",
    "turnover",
    "turnover_rate",
    "free_turnover_rate",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dividend_yield",
    "dividend_yield_ttm",
    "shares_total",
    "shares_float",
    "shares_free_float",
    "market_cap",
    "market_cap_float",
    "limit_up",
    "limit_down",
    "adj_factor",
)


@dataclass
class SyncStats:
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    messages: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.messages is None:
            self.messages = []


def _guess_ts_code(table_name: str) -> str:
    """Infer ts_code from a table name like '000001' -> '000001.SZ'."""
    base = table_name.strip().upper()
    base = base.split(".")[0]
    if base.isdigit() and len(base) <= 6:
        base = base.zfill(6)
    prefix = base[:1]
    if prefix == "6":
        return f"{base}.SH"
    if prefix in ("0", "3"):
        return f"{base}.SZ"
    if prefix in ("4", "8"):
        return f"{base}.BJ"
    # fallback: treat as SH to avoid errors
    return f"{base}.SH"


def _ensure_table(conn: sqlite3.Connection, table: str) -> List[str]:
    """Ensure the table exists, return existing column names."""
    escaped = table.replace('"', '""')
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    exists = cursor.fetchone() is not None
    if not exists:
        cols_def = ", ".join(f'"{col}" TEXT' for col in DEFAULT_COLUMNS)
        conn.execute(f'CREATE TABLE "{escaped}" ({cols_def})')
        conn.commit()
        return list(DEFAULT_COLUMNS)

    cur = conn.execute(f'PRAGMA table_info("{escaped}")')
    return [row[1] for row in cur.fetchall()]


def _delete_overlap(conn: sqlite3.Connection, table: str, min_date: str) -> None:
    escaped = table.replace('"', '""')
    conn.execute(f'DELETE FROM "{escaped}" WHERE date >= ?', (min_date,))
    conn.commit()


def _delete_exact_date(conn: sqlite3.Connection, table: str, date_str: str) -> None:
    """Delete rows for an exact trade date to avoid重复插入同日数据."""
    escaped = table.replace('"', '""')
    conn.execute(f'DELETE FROM "{escaped}" WHERE date = ?', (date_str,))


def _normalize_df(df: pd.DataFrame, ts_code: str, target_columns: List[str]) -> pd.DataFrame:
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    df["date"] = df["trade_date"].dt.strftime("%Y-%m-%d")
    df["symbol"] = ts_code.split(".")[0]
    df["ts_code"] = ts_code
    df["prev_close"] = df.get("pre_close")
    df["chg_amount"] = df.get("change")
    df["chg_pct"] = df.get("pct_chg")
    df["volume_hand"] = df.get("vol")
    df["volume"] = df.get("vol") * 100 if "vol" in df.columns else None
    df["turnover_k"] = df.get("amount")  # tushare 日线 amount 单位: 千元
    df["turnover"] = df["turnover_k"] * 1000 if "turnover_k" in df.columns else None

    # Keep only columns that exist in table.
    present_cols = [col for col in DEFAULT_COLUMNS if col in target_columns]
    usable = [col for col in present_cols if col in df.columns]
    # Ensure required basics
    required = ["symbol", "ts_code", "date", "open", "high", "low", "close", "volume"]
    for col in required:
        if col in target_columns and col not in usable:
            usable.append(col)
    return df[usable]


def sync_tushare_daily(
    *,
    db_path: Path,
    token: str,
    tables: Optional[Iterable[str]] = None,
    lookback_days: int = 730,
    progress: Optional[Callable[[str], None]] = None,
) -> SyncStats:
    """Incrementally sync daily bars from Tushare into per-symbol tables (逐个 symbol 拉取，适合小批量补齐)."""
    stats = SyncStats()
    if ts is None:
        raise RuntimeError(f"tushare 未安装: {_TS_IMPORT_ERROR}")
    if not token:
        raise ValueError("缺少 Tushare token")

    pro = ts.pro_api(token)
    db_path = Path(db_path)
    if progress:
        progress(f"使用数据库: {db_path}")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")

        if tables is None:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            tables = [row[0] for row in rows]

        tables = list(tables)
        total = len(tables)
        if progress:
            progress(f"待同步股票数: {total}")

        window_start = time.monotonic()
        request_count = 0

        for idx, table in enumerate(tables, 1):
            ts_code = _guess_ts_code(str(table))
            escaped_table = str(table).replace('"', '""')
            try:
                row = conn.execute(
                    f'SELECT MAX(date) FROM "{escaped_table}"'
                ).fetchone()
                last_date_raw = row[0] if row else None
            except Exception:
                last_date_raw = None

            start_date = None
            if last_date_raw:
                try:
                    dt = datetime.fromisoformat(str(last_date_raw))
                except Exception:
                    dt = None
                if dt:
                    start_date = dt.strftime("%Y%m%d")
            if not start_date:
                start_date = (datetime.now() - timedelta(days=lookback_days)).strftime(
                    "%Y%m%d"
                )

            # 简单的速率控制：每 480 次请求休眠至 60s 窗口结束
            now = time.monotonic()
            elapsed = now - window_start
            if elapsed >= 60:
                window_start = now
                request_count = 0
            if request_count >= 480:
                sleep_for = max(0, 60 - elapsed + 2)
                if progress:
                    progress(f"触发限速，暂停 {sleep_for:.0f}s...")
                time.sleep(sleep_for)
                window_start = time.monotonic()
                request_count = 0

            if progress:
                progress(f"[{idx}/{total}] {table} ({ts_code}) 从 {start_date} 开始同步")

            attempts = 0
            df = pd.DataFrame()
            while attempts < 3:
                attempts += 1
                try:
                    df = pro.daily(ts_code=ts_code, start_date=start_date)
                    break
                except Exception as exc:
                    wait = 2 * attempts + attempts
                    if attempts >= 3:
                        if progress:
                            progress(f"{table} 拉取失败: {exc}")
                        stats.failed += 1
                        stats.messages.append(f"{table} failed: {exc}")
                        df = pd.DataFrame()
                        break
                    if progress:
                        progress(f"{table} 请求失败，第 {attempts} 次重试，等待 {wait}s...")
                    time.sleep(wait)

            request_count += 1
            time.sleep(0.15)

            if df.empty:
                stats.skipped += 1
                continue

            try:
                target_columns = _ensure_table(conn, str(table))
                df_norm = _normalize_df(df, ts_code, target_columns)
                if df_norm.empty:
                    stats.skipped += 1
                    continue
                min_date = df_norm["date"].min()
                _delete_overlap(conn, str(table), min_date)
                df_norm.to_sql(
                    str(table),
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                    chunksize=1000,
                )
                stats.succeeded += 1
            except Exception as exc:
                stats.failed += 1
                stats.messages.append(f"{table} 写入失败: {exc}")
                if progress:
                    progress(f"{table} 写入失败: {exc}")

    return stats


def sync_tushare_daily_by_date(
    *,
    db_path: Path,
    token: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 120,
    tables_hint: Optional[List[str]] = None,
    progress: Optional[Callable[[str], None]] = None,
    progress_count: Optional[Callable[[int, int], None]] = None,
    use_trade_cal: bool = False,
) -> SyncStats:
    """
    更高效的按交易日批量补齐：每个交易日 1 次请求，返回全市场数据，再拆分写入各股票表。
    利用 Tushare 每分钟 50 次调用/每次 6000 行的额度，适合覆盖最近缺失区间。
    """
    stats = SyncStats()
    if ts is None:
        raise RuntimeError(f"tushare 未安装: {_TS_IMPORT_ERROR}")
    if not token:
        raise ValueError("缺少 Tushare token")

    pro = ts.pro_api(token)
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")

        today = datetime.now().strftime("%Y%m%d")
        if end_date is None:
            end_date = today
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        # 获取交易日历；默认不调用 trade_cal（适配只有 daily 权限），直接用工作日推算。
        trade_dates: List[str] = []
        if use_trade_cal:
            try:
                cal = pro.trade_cal(
                    start_date=start_date,
                    end_date=end_date,
                    is_open=1,
                    fields="cal_date,is_open",
                )
                trade_dates = sorted(cal["cal_date"].astype(str).tolist())
            except Exception as exc:
                if progress:
                    progress(f"trade_cal 调用失败，改用工作日推算: {exc}")
        if not trade_dates:
            start_dt = datetime.strptime(start_date, "%Y%m%d")
            end_dt = datetime.strptime(end_date, "%Y%m%d")
            cur = start_dt
            while cur <= end_dt:
                if cur.weekday() < 5:  # 周一到周五
                    trade_dates.append(cur.strftime("%Y%m%d"))
                cur += timedelta(days=1)
        total = len(trade_dates)
        if progress:
            progress(f"按交易日同步，日期范围 {start_date} -> {today}，共 {total} 个交易日")

        window_start = time.monotonic()
        request_count = 0

        total_tables_hint = len(tables_hint) if tables_hint else None
        overall_total = (total_tables_hint * total) if total_tables_hint else None
        processed_global = 0

        name_cache: Dict[str, Optional[str]] = {}

        for idx, trade_date in enumerate(trade_dates, 1):
            # 速率控制：50 次/分钟，给余量设 48
            now = time.monotonic()
            elapsed = now - window_start
            if elapsed >= 60:
                window_start = now
                request_count = 0
            if request_count >= 48:
                sleep_for = max(0, 60 - elapsed + 1)
                if progress:
                    progress(f"触发限速，等待 {sleep_for:.0f}s 再继续...")
                time.sleep(sleep_for)
                window_start = time.monotonic()
                request_count = 0

            if progress:
                progress(f"[{idx}/{total}] 拉取交易日 {trade_date}")

            attempts = 0
            df = pd.DataFrame()
            while attempts < 3:
                attempts += 1
                try:
                    df = pro.daily(trade_date=trade_date)
                    break
                except Exception as exc:
                    wait = 2 * attempts + attempts
                    if attempts >= 3:
                        stats.failed += 1
                        stats.messages.append(f"{trade_date} 请求失败: {exc}")
                        if progress:
                            progress(f"{trade_date} 请求失败: {exc}")
                        break
                    time.sleep(wait)

            request_count += 1
            time.sleep(0.1)

            if df.empty:
                stats.skipped += 1
                if progress:
                    progress(f"{trade_date} 无返回数据，跳过")
                continue

            grouped: Dict[str, List[Tuple]] = {}
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code", "")).strip()
                if not ts_code:
                    continue
                symbol = ts_code.split(".")[0].zfill(6)
                table = symbol
                trade_date_str = datetime.strptime(row["trade_date"], "%Y%m%d").strftime("%Y-%m-%d")
                grouped.setdefault(table, []).append(
                    (
                        symbol,
                        row.get("name", None),
                        None,
                        None,
                        None,
                        ts_code,
                        trade_date_str,
                        row.get("open"),
                        row.get("high"),
                        row.get("low"),
                        row.get("close"),
                        row.get("pre_close"),
                        row.get("change"),
                        row.get("pct_chg"),
                        row.get("vol"),
                        (row.get("vol") or 0) * 100,
                        row.get("amount"),
                        (row.get("amount") or 0) * 1000 if row.get("amount") is not None else None,
                        None,
                        None,
                        None,
                        row.get("pe"),
                        None,
                        row.get("pb"),
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                )

            total_tables_today = len(grouped)
            if progress_count:
                day_total = total_tables_hint or total_tables_today
                progress_count(processed_global, overall_total or processed_global + day_total)

            processed_today = 0
            for table, rows in grouped.items():
                try:
                    target_cols = _ensure_table(conn, table)
                    placeholders = ",".join(["?"] * len(target_cols))
                    col_names = ",".join(f'"{c}"' for c in target_cols)
                    target_len = len(target_cols)

                    known_name = name_cache.get(table)
                    if known_name is None and "name" in target_cols:
                        try:
                            escaped = table.replace('"', '""')
                            res = conn.execute(
                                f'SELECT name FROM "{escaped}" WHERE name IS NOT NULL ORDER BY rowid DESC LIMIT 1'
                            ).fetchone()
                            if res and res[0]:
                                known_name = str(res[0])
                                name_cache[table] = known_name
                        except Exception:
                            known_name = None
                            name_cache[table] = None

                    name_idx = target_cols.index("name") if "name" in target_cols else -1

                    def _pad_row(item: Tuple) -> Tuple:
                        buff = list(item)
                        if name_idx >= 0:
                            # 确保索引存在
                            while len(buff) <= name_idx:
                                buff.append(None)
                            if (buff[name_idx] is None or buff[name_idx] == "") and known_name:
                                buff[name_idx] = known_name
                        if len(buff) < target_len:
                            buff.extend([None] * (target_len - len(buff)))
                        return tuple(buff[:target_len])

                    data_rows = [_pad_row(item) for item in rows]
                    safe_table = table.replace('"', '""')
                    trade_date_str = rows[0][6] if len(rows[0]) > 6 else None  # index 6 is date in tuple

                    conn.execute("BEGIN")
                    if trade_date_str:
                        _delete_exact_date(conn, table, trade_date_str)
                    conn.executemany(
                        f'INSERT INTO "{safe_table}" ({col_names}) VALUES ({placeholders})',
                        data_rows,
                    )
                    conn.commit()
                    stats.succeeded += 1
                    processed_today += 1
                    processed_global += 1
                    if progress:
                        progress(f"入库 {table} @ {trade_date_str} 插入 {len(data_rows)} 行")
                    if progress_count:
                        day_total = total_tables_hint or total_tables_today or processed_today
                        progress_count(processed_global, overall_total or processed_global + (day_total - processed_today))
                except Exception as exc:
                    conn.rollback()
                    stats.failed += 1
                    stats.messages.append(f"{table}({trade_date}) 写入失败: {exc}")
                    if progress:
                        progress(f"{table}({trade_date}) 写入失败: {exc}")

            if progress:
                progress(
                    f"{trade_date} 完成：{len(grouped)} 只股票，{len(df)} 行；累计 成功 {stats.succeeded} / 失败 {stats.failed} / 跳过 {stats.skipped}"
                )

    return stats


__all__ = ["sync_tushare_daily", "sync_tushare_daily_by_date", "SyncStats"]
