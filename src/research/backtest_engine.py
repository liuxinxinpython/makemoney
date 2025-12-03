from __future__ import annotations

import random
from datetime import timedelta
from typing import Dict, List

from PyQt5 import QtCore  # type: ignore[import-not-found]

from .models import BacktestRequest, BacktestResult, StrategyContext
from .strategy_registry import StrategyRegistry


class BacktestEngine(QtCore.QObject):
    """Lightweight backtest runner.

    当前实现为占位符：按天遍历历史数据并调用策略生成信号，
    一旦有真实交易/指标逻辑，可在此扩展。
    """

    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(BacktestResult)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, registry: StrategyRegistry, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.registry = registry

    def run(self, request: BacktestRequest, db_path) -> None:  # type: ignore[override]
        try:
            result = self._execute(request, db_path)
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - runtime feedback
            self.failed.emit(str(exc))

    # ------------------------------------------------------------------
    def _execute(self, request: BacktestRequest, db_path) -> BacktestResult:
        metrics = {
            "initial_cash": request.initial_cash,
            "net_profit": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }
        equity_curve: List[Dict[str, float]] = []
        trades: List[Dict[str, float]] = []

        # Placeholder logic: simply mark random performance so UI can show results
        random.seed(len(request.universe) + int(request.initial_cash))
        net = request.initial_cash
        drawdown = 0.0

        for idx, symbol in enumerate(request.universe):
            self.progress.emit(f"回测 {symbol} ({idx + 1}/{len(request.universe)})")
            context = StrategyContext(
                db_path=db_path,
                table_name=symbol,
                symbol=symbol,
                params=request.params,
                current_only=False,
            )
            run_result = self.registry.run_strategy(request.strategy_key, context)
            signal_count = len(run_result.markers)
            pnl = (signal_count % 5 - 2) * 0.01 * net  # mock profit
            net += pnl
            drawdown = min(drawdown, pnl)
            equity_curve.append({"symbol": symbol, "value": net})
            if signal_count:
                trades.append({
                    "symbol": symbol,
                    "signals": signal_count,
                    "pnl": round(pnl, 2),
                })

        metrics["net_profit"] = round(net - request.initial_cash, 2)
        metrics["max_drawdown"] = round(drawdown, 2)
        if len(equity_curve) > 1:
            metrics["sharpe"] = round(metrics["net_profit"] / (abs(drawdown) + 1e-6), 2)

        return BacktestResult(
            strategy_key=request.strategy_key,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            notes="当前回测为占位符，仅用于演示 UI 流程。",
        )
