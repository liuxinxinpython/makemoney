from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from ..data.data_loader import load_candles_from_sqlite
    HAS_DATA_LOADER = True
except Exception:  # pragma: no cover - optional import
    load_candles_from_sqlite = None
    HAS_DATA_LOADER = False

try:
    from ..displays import DisplayResult  # type: ignore[import-not-found]
    HAS_DISPLAY = True
except Exception:  # pragma: no cover - optional import
    DisplayResult = None
    HAS_DISPLAY = False

try:
    from ..research import StrategyContext, StrategyRunResult
    from ..research.models import StrategyParameter
except Exception:  # pragma: no cover - optional import
    StrategyContext = None
    StrategyRunResult = None
    StrategyParameter = None

from .helpers import serialize_run_result


if StrategyParameter is not None:
    CHAN_STRATEGY_PARAMETERS: List[StrategyParameter] = [
        StrategyParameter(
            key="swing_window",
            label="分型窗口",
            type="number",
            default=3,
            description="检测分型时向前向后比较的K线数量",
        ),
        StrategyParameter(
            key="min_move_pct",
            label="最小笔幅度(%)",
            type="number",
            default=3.0,
            description="小于该幅度的波动不构成有效笔",
        ),
        StrategyParameter(
            key="divergence_pct",
            label="背驰阈值(%)",
            type="number",
            default=5.0,
            description="一二买卖判断时要求的高低点抬升/下降幅度",
        ),
    ]
else:  # pragma: no cover - optional UI metadata
    CHAN_STRATEGY_PARAMETERS = []


@dataclass
class Fractal:
    index: int
    time: str
    price: float
    kind: str  # 'top' 或 'bottom'


@dataclass
class Stroke:
    start: Fractal
    end: Fractal
    direction: str  # 'up' 或 'down'
    amplitude: float


@dataclass
class ChanSignal:
    label: str
    category: str  # 'buy' 或 'sell'
    fractal: Fractal
    strength: float
    reason: str

    def to_marker(self, sequence: int) -> Dict[str, Any]:
        color = '#4caf50' if self.category == 'buy' else '#f44336'
        position = 'belowBar' if self.category == 'buy' else 'aboveBar'
        shape = 'arrowUp' if self.category == 'buy' else 'arrowDown'
        return {
            'id': f'chan_{self.category}_{sequence}',
            'time': self.fractal.time,
            'position': position,
            'shape': shape,
            'color': color,
            'text': f"{self.label} {self.fractal.price:.2f} ({self.reason})",
            'size': 2,
            'price': self.fractal.price,
        }


class ChanTheoryAnalyzer:
    def __init__(self, candles: List[Dict[str, Any]], swing_window: int, min_move: float, divergence: float):
        self.candles = candles
        self.swing_window = max(2, swing_window)
        self.min_move = max(0.0005, min_move)
        self.divergence = max(0.0005, divergence)
        self._cutoff_days = 365

    def run(self) -> Dict[str, Any]:
        if len(self.candles) < (self.swing_window * 2 + 5):
            return {
                'markers': [],
                'overlays': [],
                'signals': [],
                'stats': {'stroke_count': 0, 'zone_count': 0, 'buy_signals': 0, 'sell_signals': 0},
                'strokes': [],
            }
        cutoff_dt = self._cutoff_datetime()
        fractals = self._detect_fractals()
        strokes = self._build_strokes(fractals)
        zones = self._build_zones(strokes)
        signals = self._detect_signals(strokes)
        markers = self._build_markers(signals, cutoff_dt)
        overlays = self._build_overlays(zones, cutoff_dt)
        strokes_payload = [
            {
                'startTime': stroke.start.time,
                'endTime': stroke.end.time,
                'startPrice': stroke.start.price,
                'endPrice': stroke.end.price,
                'direction': stroke.direction,
            }
            for stroke in strokes
        ]

        stats = {
            'stroke_count': len(strokes),
            'zone_count': len(zones),
            'buy_signals': sum(1 for s in signals if s.category == 'buy'),
            'sell_signals': sum(1 for s in signals if s.category == 'sell'),
        }
        return {'markers': markers, 'overlays': overlays, 'signals': signals, 'stats': stats, 'strokes': strokes_payload}

    def _cutoff_datetime(self) -> Optional[datetime]:
        latest = None
        for candle in self.candles:
            ts = self._parse_time_value(candle.get('time'))
            if ts and (latest is None or ts > latest):
                latest = ts
        if latest is None:
            return None
        return latest - timedelta(days=self._cutoff_days)

    @staticmethod
    def _parse_time_value(value: Union[str, float, int, datetime, None]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            try:
                return datetime.utcfromtimestamp(float(value))
            except ValueError:
                return None
        text = str(value)
        candidates = [
            ("%Y-%m-%d", text[:10]),
            ("%Y/%m/%d", text[:10]),
            ("%Y%m%d", text[:8]),
        ]
        for fmt, sample in candidates:
            try:
                return datetime.strptime(sample, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _detect_fractals(self) -> List[Fractal]:
        results: List[Fractal] = []
        win = self.swing_window
        last_top: Optional[Fractal] = None
        last_bottom: Optional[Fractal] = None
        for idx in range(win, len(self.candles) - win):
            high = self.candles[idx]['high']
            low = self.candles[idx]['low']
            is_top = all(high >= self.candles[j]['high'] for j in range(idx - win, idx + win + 1))
            is_bottom = all(low <= self.candles[j]['low'] for j in range(idx - win, idx + win + 1))
            time_value = str(self.candles[idx]['time'])
            if is_top:
                fractal = Fractal(idx, time_value, float(high), 'top')
                if last_top is None or fractal.price >= last_top.price or fractal.index - last_top.index >= win:
                    last_top = fractal
                    results.append(fractal)
            elif is_bottom:
                fractal = Fractal(idx, time_value, float(low), 'bottom')
                if last_bottom is None or fractal.price <= last_bottom.price or fractal.index - last_bottom.index >= win:
                    last_bottom = fractal
                    results.append(fractal)
        results.sort(key=lambda f: f.index)
        return results

    def _build_strokes(self, fractals: List[Fractal]) -> List[Stroke]:
        strokes: List[Stroke] = []
        if not fractals:
            return strokes
        anchor = fractals[0]
        for point in fractals[1:]:
            if point.kind == anchor.kind:
                if (point.kind == 'top' and point.price > anchor.price) or (point.kind == 'bottom' and point.price < anchor.price):
                    anchor = point
                continue
            amplitude = abs(point.price - anchor.price) / max(anchor.price, 1e-6)
            if amplitude < self.min_move:
                if (point.kind == 'top' and point.price > anchor.price) or (point.kind == 'bottom' and point.price < anchor.price):
                    anchor = point
                continue
            direction = 'up' if point.price > anchor.price else 'down'
            strokes.append(Stroke(anchor, point, direction, amplitude))
            anchor = point
        return strokes

    def _build_zones(self, strokes: List[Stroke]) -> List[Dict[str, Any]]:
        zones: List[Dict[str, Any]] = []
        if len(strokes) < 3:
            return zones
        counter = 1
        for idx in range(2, len(strokes)):
            s1, s2, s3 = strokes[idx - 2], strokes[idx - 1], strokes[idx]
            highs = [max(s1.start.price, s1.end.price), max(s2.start.price, s2.end.price), max(s3.start.price, s3.end.price)]
            lows = [min(s1.start.price, s1.end.price), min(s2.start.price, s2.end.price), min(s3.start.price, s3.end.price)]
            zone_top = min(highs)
            zone_bottom = max(lows)
            if zone_top <= zone_bottom:
                continue
            zones.append({
                'index': counter,
                'start_time': s1.start.time,
                'end_time': s3.end.time,
                'top': zone_top,
                'bottom': zone_bottom,
            })
            counter += 1
        return zones

    def _detect_signals(self, strokes: List[Stroke]) -> List[ChanSignal]:
        signals: List[ChanSignal] = []
        for idx in range(1, len(strokes)):
            prev = strokes[idx - 1]
            curr = strokes[idx]
            if prev.direction == 'down' and curr.direction == 'up':
                reason = f"跌{prev.amplitude * 100:.1f}%↗涨{curr.amplitude * 100:.1f}%"
                signals.append(ChanSignal('一买', 'buy', prev.end, max(prev.amplitude, curr.amplitude), reason))
            elif prev.direction == 'up' and curr.direction == 'down':
                reason = f"涨{prev.amplitude * 100:.1f}%↘跌{curr.amplitude * 100:.1f}%"
                signals.append(ChanSignal('一卖', 'sell', prev.end, max(prev.amplitude, curr.amplitude), reason))

        for idx in range(2, len(strokes)):
            s1, s2, s3 = strokes[idx - 2], strokes[idx - 1], strokes[idx]
            if s1.direction == 'down' and s2.direction == 'up' and s3.direction == 'down':
                if s3.end.price > s1.end.price and ((s3.end.price - s1.end.price) / max(s1.end.price, 1e-6)) >= self.divergence:
                    reason = f"高低点抬升{(s3.end.price - s1.end.price) / max(s1.end.price, 1e-6) * 100:.1f}%"
                    signals.append(ChanSignal('二买', 'buy', s3.end, s2.amplitude, reason))
            if s1.direction == 'up' and s2.direction == 'down' and s3.direction == 'up':
                if s3.end.price < s1.end.price and ((s1.end.price - s3.end.price) / max(s1.end.price, 1e-6)) >= self.divergence:
                    reason = f"高点下降{(s1.end.price - s3.end.price) / max(s1.end.price, 1e-6) * 100:.1f}%"
                    signals.append(ChanSignal('二卖', 'sell', s3.end, s2.amplitude, reason))
        return signals

    def _build_markers(self, signals: List[ChanSignal], cutoff: Optional[datetime]) -> List[Dict[str, Any]]:
        markers: List[Dict[str, Any]] = []
        for idx, signal in enumerate(signals, start=1):
            if cutoff:
                ts = self._parse_time_value(signal.fractal.time)
                if ts and ts < cutoff:
                    continue
            markers.append(signal.to_marker(idx))
        return markers

    def _build_overlays(self, zones: List[Dict[str, Any]], cutoff: Optional[datetime]) -> List[Dict[str, Any]]:
        overlays: List[Dict[str, Any]] = []
        for zone in zones:
            if cutoff:
                end_ts = self._parse_time_value(zone['end_time'])
                if end_ts and end_ts < cutoff:
                    continue
            overlays.append({
                'startTime': zone['start_time'],
                'endTime': zone['end_time'],
                'top': zone['top'],
                'bottom': zone['bottom'],
                'kind': 'sideways',
                'label': f"中枢#{zone['index']}",
                'color': 'rgba(255,215,0,0.18)',
            })
        return overlays


class ChanTheoryStrategy:
    def __init__(self, *, swing_window: int = 3, min_move_pct: float = 0.03, divergence_pct: float = 0.05):
        if not HAS_DATA_LOADER:
            raise ImportError('缺少 data_loader 模块，无法加载K线数据')
        self.swing_window = max(2, int(swing_window))
        self.min_move_pct = max(0.0005, float(min_move_pct))
        self.divergence_pct = max(0.0005, float(divergence_pct))

    def scan_current_symbol(self, db_path: Path, table_name: str) -> Optional[Any]:
        data = load_candles_from_sqlite(db_path, table_name)
        if data is None:
            raise ValueError(f'无法加载股票 {table_name} 的数据')
        candles, _volumes, _instrument = data
        analyzer = ChanTheoryAnalyzer(candles, self.swing_window, self.min_move_pct, self.divergence_pct)
        result = analyzer.run()
        markers = result['markers']
        overlays = result['overlays']
        stats = result['stats']
        strokes = result.get('strokes', [])
        status_message = (
            f"缠论识别: {stats['stroke_count']} 笔, {stats['zone_count']} 中枢, "
            f"买点 {stats['buy_signals']} / 卖点 {stats['sell_signals']}"
        )
        if HAS_DISPLAY:
            return DisplayResult(
                strategy_name='chan_theory',
                markers=markers,
                overlays=overlays,
                status_message=status_message,
                extra_data={'strokes': strokes},
            )
        return {
            'strategy_name': 'chan_theory',
            'markers': markers,
            'overlays': overlays,
            'status_message': status_message,
            'extra_data': {'strokes': strokes},
        }


def run_chan_workbench(context: "StrategyContext") -> "StrategyRunResult":
    if StrategyContext is None or StrategyRunResult is None:
        raise RuntimeError('策略运行环境不可用')
    params = context.params or {}

    def _get_float(key: str, default: float) -> float:
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            return default

    def _get_int(key: str, default: int) -> int:
        try:
            return int(float(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    swing_window = max(2, _get_int('swing_window', 3))
    min_move_pct = max(0.0005, _get_float('min_move_pct', 3.0) / 100.0)
    divergence_pct = max(0.0005, _get_float('divergence_pct', 5.0) / 100.0)

    strategy = ChanTheoryStrategy(
        swing_window=swing_window,
        min_move_pct=min_move_pct,
        divergence_pct=divergence_pct,
    )
    raw_result = strategy.scan_current_symbol(context.db_path, context.table_name)
    return serialize_run_result('chan_theory', raw_result)

__all__ = ['ChanTheoryStrategy', 'CHAN_STRATEGY_PARAMETERS', 'run_chan_workbench']
