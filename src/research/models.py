from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass(slots=True)
class StrategyParameter:
    """Metadata for a configurable strategy parameter."""

    key: str
    label: str
    type: str = "text"  # text, number, select, date
    default: Any = None
    description: str = ""
    options: Optional[List[Any]] = None


@dataclass(slots=True)
class StrategyDefinition:
    """High-level strategy description used by the registry/UI."""

    key: str
    title: str
    description: str
    handler: Callable[["StrategyContext"], "StrategyRunResult"]
    category: str = "general"
    parameters: List[StrategyParameter] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    preview_enabled: bool = True
    scanner_enabled: bool = True
    backtest_enabled: bool = True


@dataclass(slots=True)
class StrategyContext:
    """Runtime context passed to a strategy handler."""

    db_path: Path
    table_name: str
    symbol: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    current_only: bool = True  # True when just rendering preview on current chart
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    mode: str = "preview"


@dataclass(slots=True)
class StrategyRunResult:
    """Normalized output from a strategy execution."""

    strategy_name: str
    markers: List[Dict[str, Any]] = field(default_factory=list)
    overlays: List[Dict[str, Any]] = field(default_factory=list)
    annotations: List[Dict[str, Any]] = field(default_factory=list)
    status_message: Optional[str] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BacktestRequest:
    strategy_key: str
    universe: List[str]
    start_date: Optional[date]
    end_date: Optional[date]
    initial_cash: float = 1_000_000.0
    params: Dict[str, Any] = field(default_factory=dict)
    max_positions: int = 5
    position_pct: float = 0.2  # fraction of equity per new position
    commission_rate: float = 0.0003
    slippage: float = 0.0005


@dataclass(slots=True)
class BacktestResult:
    strategy_key: str
    metrics: Dict[str, Any]
    equity_curve: List[Dict[str, Any]]
    trades: List[Dict[str, Any]]
    notes: str = ""


@dataclass(slots=True)
class ScanRequest:
    strategy_key: str
    universe: List[str]
    start_date: Optional[date]
    end_date: Optional[date]
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScanResult:
    strategy_key: str
    symbol: str
    table_name: str
    score: float
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    confidence: Optional[float] = None
    signals: List[Dict[str, Any]] = field(default_factory=list)
    extra_signals: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
