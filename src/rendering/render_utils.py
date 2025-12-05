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

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

TEMPLATE_FILENAME = "tradingview_template.html"
TEMPLATE_PATH = Path(__file__).parent / "templates" / TEMPLATE_FILENAME
ECHARTS_TEMPLATE_PATH = Path(__file__).parent / "templates" / "echarts_demo.html"
ECHARTS_PREVIEW_TEMPLATE_PATH = Path(__file__).parent / "templates" / "echarts_preview.html"
BACKTEST_EQUITY_TEMPLATE_PATH = Path(__file__).parent / "templates" / "backtest_equity.html"


class SafeJSONEncoder(json.JSONEncoder):
    """
    JSON Encoder that handles:
    1. Numpy types (int, float, array) - Compatible with NumPy 1.x and 2.x
    2. NaN/Inf values (converts to None)
    """
    def default(self, obj):
        if HAS_NUMPY:
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                if np.isnan(obj) or np.isinf(obj):
                    return None
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
        
        return super().default(obj)


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

    # Use SafeJSONEncoder to handle potential numpy types and NaNs
    return (
        template.replace("__CANDLES__", json.dumps(candles, cls=SafeJSONEncoder))
        .replace("__VOLUMES__", json.dumps(volumes, cls=SafeJSONEncoder))
        .replace("__INSTRUMENT__", json.dumps(instrument_payload, ensure_ascii=False))
        .replace("__SIGNALS__", json.dumps(markers or [], cls=SafeJSONEncoder))
        .replace("__OVERLAYS__", json.dumps(overlays or [], cls=SafeJSONEncoder))
    )


def render_echarts_demo(
    candles: List[Dict[str, float]],
    markers: Optional[List[Dict[str, Any]]] = None,
    overlays: Optional[List[Dict[str, Any]]] = None,
) -> str:
    try:
        template = ECHARTS_TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到模板文件 {ECHARTS_TEMPLATE_PATH}。") from exc

    return (
        template.replace("__CANDLES__", json.dumps(candles or [], cls=SafeJSONEncoder))
        .replace("__MARKERS__", json.dumps(markers or [], cls=SafeJSONEncoder))
        .replace("__OVERLAYS__", json.dumps(overlays or [], cls=SafeJSONEncoder))
    )


def render_echarts_preview(
    candles: List[Dict[str, float]],
    volumes: Optional[List[Dict[str, float]]] = None,
    markers: Optional[List[Dict[str, Any]]] = None,
    overlays: Optional[List[Dict[str, Any]]] = None,
    instrument: Optional[Dict[str, Any]] = None,
    strokes: Optional[List[Dict[str, Any]]] = None,
    title: str = "ECharts 策略预览",
) -> str:
    try:
        template = ECHARTS_PREVIEW_TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到模板文件 {ECHARTS_PREVIEW_TEMPLATE_PATH}。") from exc

    instrument_payload: Dict[str, Any] = {
        "symbol": "",
        "name": "",
        "display": title,
        "exchange": "",
    }
    if instrument:
        for key in ("symbol", "name", "display", "exchange"):
            value = None
            if isinstance(instrument, dict):
                value = instrument.get(key)
            else:
                value = getattr(instrument, key, None)
            if value:
                instrument_payload[key] = value
        if not instrument_payload["display"]:
            if instrument_payload["symbol"] and instrument_payload["name"]:
                instrument_payload["display"] = f"{instrument_payload['symbol']} · {instrument_payload['name']}"
            else:
                instrument_payload["display"] = instrument_payload.get("symbol") or instrument_payload.get("name") or title

    return (
        template.replace("__TITLE__", title)
        .replace("__CANDLES__", json.dumps(candles or [], cls=SafeJSONEncoder))
        .replace("__VOLUMES__", json.dumps(volumes or [], cls=SafeJSONEncoder))
        .replace("__MARKERS__", json.dumps(markers or [], cls=SafeJSONEncoder))
        .replace("__OVERLAYS__", json.dumps(overlays or [], cls=SafeJSONEncoder))
        .replace("__STROKES__", json.dumps(strokes or [], cls=SafeJSONEncoder))
        .replace("__INSTRUMENT__", json.dumps(instrument_payload, ensure_ascii=False))
    )


def render_backtest_equity(
    equity_curve: Optional[List[Dict[str, Any]]],
    trades: Optional[List[Dict[str, Any]]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    *,
    title: str = "收益曲线",
) -> str:
    try:
        template = BACKTEST_EQUITY_TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到模板文件 {BACKTEST_EQUITY_TEMPLATE_PATH}。") from exc

    metrics_payload = metrics or {}
    return (
        template.replace("__TITLE_TEXT__", title)
        .replace("__TITLE_JSON__", json.dumps(title, ensure_ascii=False))
        .replace("__EQUITY__", json.dumps(equity_curve or [], cls=SafeJSONEncoder))
        .replace("__TRADES__", json.dumps(trades or [], cls=SafeJSONEncoder))
        .replace("__METRICS__", json.dumps(metrics_payload, cls=SafeJSONEncoder))
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