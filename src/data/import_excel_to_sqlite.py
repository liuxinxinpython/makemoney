"""Bulk-import A-share daily Excel/CSV files into a SQLite database.

Usage (PowerShell):
  python import_excel_to_sqlite.py -d C:\path\to\excel_dir -o a_share_daily.db
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

# Mapping from Excel column names to normalized output names.
COLUMN_MAP: Dict[str, str] = {
    "股票代码": "symbol",
    "名称": "name",
    "所属行业": "industry",
    "地域": "region",
    "上市日期": "list_date",
    "TS代码": "ts_code",
    "交易日期": "date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "前收盘价": "prev_close",
    "涨跌额": "chg_amount",
    "涨跌幅(%)": "chg_pct",
    "成交量(手)": "volume_hand",
    "成交额(千元)": "turnover_k",
    "换手率(%)": "turnover_rate",
    "换手率(自由流通股)": "free_turnover_rate",
    "量比": "volume_ratio",
    "市盈率": "pe",
    "市盈率(TTM,亏损的PE为空)": "pe_ttm",
    "市净率": "pb",
    "市销率": "ps",
    "市销率(TTM)": "ps_ttm",
    "股息率(%)": "dividend_yield",
    "股息率(TTM)(%)": "dividend_yield_ttm",
    "总股本(万股)": "shares_total",
    "流通股本(万股)": "shares_float",
    "自由流通股本(万股)": "shares_free_float",
    "总市值(万元)": "market_cap",
    "流通市值(万元)": "market_cap_float",
    "今日涨停价": "limit_up",
    "今日跌停价": "limit_down",
    "复权因子": "adj_factor",
}

# Columns to persist in the SQLite table (ordered).
OUTPUT_COLUMNS: Iterable[str] = (
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


REQUIRED_RAW_COLUMNS: Iterable[str] = (
    "交易日期",
    "开盘价",
    "最高价",
    "最低价",
    "收盘价",
    "成交量(手)",
    "成交额(千元)",
)


def normalize_dataframe(df: pd.DataFrame, symbol_hint: Optional[str] = None) -> pd.DataFrame:
    """Rename/transform raw Excel columns to a clean schema."""
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    symbol_hint_norm: Optional[str] = None
    if symbol_hint:
        symbol_hint_norm = symbol_hint.strip().upper()

    missing_required = [col for col in REQUIRED_RAW_COLUMNS if col not in df.columns]
    if missing_required:
        raise ValueError(f"Excel 缺少关键列: {', '.join(missing_required)}")

    rename_map = {col: COLUMN_MAP[col] for col in df.columns if col in COLUMN_MAP}
    df = df.rename(columns=rename_map)

    if symbol_hint_norm:
        symbol_series = df.get("symbol")
        if symbol_series is None or symbol_series.isna().all():
            df["symbol"] = symbol_hint_norm
        else:
            df["symbol"] = symbol_series.fillna(symbol_hint_norm)

    if "symbol" in df.columns:
        df["symbol"] = (
            df["symbol"]
            .astype(str)
            .str.strip()
            .replace({"nan": pd.NA, "None": pd.NA})
        )
        df["symbol"] = (
            df["symbol"].fillna("").str.replace(r"[^0-9A-Za-z]", "", regex=True)
        )
        df["symbol"] = df["symbol"].str.upper()
        numeric_mask = df["symbol"].str.fullmatch(r"\d+").fillna(False)
        df.loc[numeric_mask, "symbol"] = df.loc[numeric_mask, "symbol"].str.zfill(6)
        if symbol_hint_norm:
            df["symbol"] = symbol_hint_norm

    # Normalize dates.
    raw_date = df["date"]
    parsed_date = pd.to_datetime(raw_date, errors="coerce")
    unrealistic_mask = parsed_date.notna() & (
        (parsed_date.dt.year < 1980) | (parsed_date.dt.year > 2100)
    )
    parsed_date.loc[unrealistic_mask] = pd.NaT

    missing_mask = parsed_date.isna() & raw_date.notna()
    if missing_mask.any():
        digits = (
            raw_date.loc[missing_mask]
            .astype(str)
            .str.strip()
            .str.replace(r"\D", "", regex=True)
        )
        digits = digits.str.zfill(8).str[:8]
        parsed_date.loc[missing_mask] = pd.to_datetime(
            digits, format="%Y%m%d", errors="coerce"
        )
    df["date"] = parsed_date
    df = df.dropna(subset=["date"])
    df = df.sort_values("date")
    df = df.drop_duplicates(subset="date", keep="last")
    df["date"] = df["date"].dt.date

    if "list_date" in df.columns:
        list_raw = df["list_date"]
        list_parsed = pd.to_datetime(list_raw, errors="coerce")
        list_unreal = list_parsed.notna() & (
            (list_parsed.dt.year < 1980) | (list_parsed.dt.year > 2100)
        )
        list_parsed.loc[list_unreal] = pd.NaT

        list_missing = list_parsed.isna() & list_raw.notna()
        if list_missing.any():
            digits = (
                list_raw.loc[list_missing]
                .astype(str)
                .str.strip()
                .str.replace(r"\D", "", regex=True)
            )
            digits = digits.str.zfill(8).str[:8]
            list_parsed.loc[list_missing] = pd.to_datetime(
                digits, format="%Y%m%d", errors="coerce"
            )
        df["list_date"] = list_parsed.dt.date

    # 成交量(手) -> 股; 千元 -> 元
    if "volume_hand" in df.columns:
        df["volume_hand"] = pd.to_numeric(df["volume_hand"], errors="coerce")
        df["volume"] = df["volume_hand"].fillna(0) * 100
    else:
        df["volume_hand"] = pd.NA
        df["volume"] = pd.NA

    if "turnover_k" in df.columns:
        df["turnover_k"] = pd.to_numeric(df["turnover_k"], errors="coerce")
        df["turnover"] = df["turnover_k"].fillna(0) * 1000
    else:
        df["turnover_k"] = pd.NA
        df["turnover"] = pd.NA

    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    return df[list(OUTPUT_COLUMNS)]


SUPPORTED_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".xlsb", ".csv"}


def import_directory(
    excel_dir: Path,
    db_path: Path,
    replace: bool,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[str]:
    excel_files = sorted(
        file
        for file in excel_dir.iterdir()
        if file.is_file() and file.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not excel_files:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise FileNotFoundError(f"目录 {excel_dir} 中未发现支持的文件类型 ({supported})")

    def log(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)
        else:
            print(message, flush=True)

    mode = "replace" if replace else "append"
    log(f"开始导入: 目录={excel_dir}, 输出={db_path}, 模式={'重建' if replace else '追加'}")
    processed: List[str] = []
    with sqlite3.connect(db_path) as conn:
        for file in excel_files:
            symbol = file.stem.lower()
            log(f"-> 处理 {symbol} ({file.name})")
            if file.suffix.lower() == ".csv":
                try:
                    raw = pd.read_csv(file, encoding="utf-8-sig")
                except UnicodeDecodeError:
                    raw = pd.read_csv(file, encoding="gb18030")
            else:
                raw = pd.read_excel(file)

            normalized = normalize_dataframe(raw, symbol_hint=symbol)
            if not normalized.empty:
                first_date = normalized["date"].min()
                last_date = normalized["date"].max()
                log(
                    "   日期范围: "
                    f"{first_date or '未知'} -> {last_date or '未知'} "
                    f"共 {len(normalized)} 行"
                )
                if first_date and hasattr(first_date, "year") and first_date.year < 1980:
                    log("   ⚠️ 检测到早于 1980 的日期，请检查原始数据的日期格式是否为 yyyymmdd")
            normalized.to_sql(symbol, conn, if_exists=mode, index=False)
            processed.append(symbol)

    log(f"导入完成，共处理 {len(processed)} 个文件，数据库位于 {db_path}")
    return processed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 A 股 Excel 日线导入 SQLite")
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        required=True,
        help="包含 Excel 文件的目录",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("a_share_daily.db"),
        help="输出 SQLite 文件路径 (默认: a_share_daily.db)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="每只股票重建表 (默认增量追加)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    excel_dir = args.directory
    db_path = args.output

    if not excel_dir.exists() or not excel_dir.is_dir():
        raise FileNotFoundError(f"无效目录: {excel_dir}")

    import_directory(excel_dir, db_path, replace=args.replace)


if __name__ == "__main__":
    main()
