from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pandas as pd  # type: ignore[import-not-found]
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None  # type: ignore[assignment]

try:
    import akshare as ak  # type: ignore[import-not-found]
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

TEMPLATE_FILENAME = "tradingview_template.html"
TEMPLATE_PATH = Path(__file__).parent / "templates" / TEMPLATE_FILENAME


def render_html(
    candles: List[Dict[str, float]],
    volumes: List[Dict[str, float]],
    instrument: Optional[Dict[str, str]] = None,
    markers: Optional[List[Dict[str, Any]]] = None,
    overlays: Optional[List[Dict[str, Any]]] = None,
) -> str:
    try:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到模板文件 {TEMPLATE_PATH}. 请确认 {TEMPLATE_FILENAME} 与脚本位于同一目录。") from exc

    instrument_payload: Dict[str, str] = {
        "symbol": "",
        "name": "",
        "display": "",
    }
    if instrument:
        instrument_payload.update({k: v for k, v in instrument.items() if isinstance(v, str)})

    symbol_text = instrument_payload.get("symbol", "")
    name_text = instrument_payload.get("name", "")
    if instrument_payload.get("display"):
        pass
    elif symbol_text and name_text:
        instrument_payload["display"] = f"{symbol_text} · {name_text}"
    elif symbol_text:
        instrument_payload["display"] = symbol_text
    elif name_text:
        instrument_payload["display"] = name_text
    else:
        instrument_payload["display"] = "未选择股票"

    return (
        template.replace("__CANDLES__", json.dumps(candles))
        .replace("__VOLUMES__", json.dumps(volumes))
        .replace("__INSTRUMENT__", json.dumps(instrument_payload, ensure_ascii=False))
        .replace("__SIGNALS__", json.dumps(markers or []))
        .replace("__OVERLAYS__", json.dumps(overlays or []))
    )


def build_mock_candles(count: int = 240) -> Tuple[List[Dict[str, float]], List[Dict[str, float]], Dict[str, str]]:
    random.seed(42)

    candles: List[Dict[str, float]] = []
    volumes: List[Dict[str, float]] = []
    current_day = (datetime.now() - timedelta(days=count)).date()
    price = 1800.0

    for _ in range(count):
        open_ = price + random.uniform(-5, 5)
        close = open_ + random.uniform(-8, 8)
        high = max(open_, close) + random.uniform(0, 4)
        low = min(open_, close) - random.uniform(0, 4)
        date_str = current_day.strftime("%Y-%m-%d")
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
                "value": round(random.uniform(5e4, 3e5) / 1e4, 2),
                "color": "#f03752" if close >= open_ else "#13b355",
            }
        )
        current_day += timedelta(days=1)
        price = close

    instrument = {"symbol": "MOCK", "name": "模拟数据"}
    return candles, volumes, instrument


def load_maotai_candles() -> Optional[Tuple[List[Dict[str, float]], List[Dict[str, float]], Dict[str, str]]]:
    if not (HAS_AKSHARE and HAS_PANDAS):
        return None

    try:
        df = ak.stock_zh_a_hist(
            symbol="600519",
            period="daily",
            start_date="19900101",
            adjust="qfq",
        )
        if df.empty:
            return None

        df = df.sort_values("日期")
        candles: List[Dict[str, float]] = []
        volumes: List[Dict[str, float]] = []

        for _, row in df.iterrows():
            ts = pd.to_datetime(row["日期"]).to_pydatetime()
            date_str = ts.strftime("%Y-%m-%d")
            open_ = float(row["开盘"]) 
            high = float(row["最高"]) 
            low = float(row["最低"]) 
            close = float(row["收盘"]) 
            volume = float(row["成交量"]) * 100  # 成交量单位为手 -> 股
            volume_wan = round(volume / 1e4, 2)

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

        instrument = {"symbol": "600519", "name": "贵州茅台"}
        return candles, volumes, instrument
    except Exception:
        return None
