from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5 import QtCore  # type: ignore[import-not-found]

from ..data.data_loader import load_candles_from_sqlite
from .models import BacktestRequest, BacktestResult, StrategyContext
from .strategy_registry import StrategyRegistry


class BacktestCancelled(RuntimeError):
    """Raised when a backtest run is cancelled."""


class BacktestWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(BacktestResult)
    failed = QtCore.pyqtSignal(str)
    cancelled = QtCore.pyqtSignal()

    def __init__(self, engine: "BacktestEngine", request: BacktestRequest, db_path: Path) -> None:
        super().__init__()
        self._engine = engine
        self._request = request
        self._db_path = db_path
        self._cancelled = False

    def run(self) -> None:
        try:
            result = self._engine._execute(
                self._request,
                self._db_path,
                progress_callback=self.progress.emit,
                cancel_callback=lambda: self._cancelled,
            )
        except BacktestCancelled:
            self.cancelled.emit()
        except Exception as exc:  # pragma: no cover - worker diagnostics
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)

    def cancel(self) -> None:
        self._cancelled = True


class BacktestEngine(QtCore.QObject):
    """Portfolio backtester that consumes strategy trades and simulates executions."""

    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(BacktestResult)
    failed = QtCore.pyqtSignal(str)
    cancelled = QtCore.pyqtSignal()

    def __init__(self, registry: StrategyRegistry, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self._worker_thread: Optional[QtCore.QThread] = None
        self._worker: Optional[BacktestWorker] = None

    def run(self, request: BacktestRequest, db_path) -> None:  # type: ignore[override]
        try:
            result = self._execute(request, Path(db_path), progress_callback=self.progress.emit)
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - runtime feedback
            self.failed.emit(str(exc))

    def run_async(self, request: BacktestRequest, db_path) -> None:
        if self._worker_thread is not None:
            raise RuntimeError("回测任务仍在运行，无法重复启动。")
        thread = QtCore.QThread()
        worker = BacktestWorker(self, request, Path(db_path))
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self.progress.emit)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.cancelled.connect(self._on_worker_cancelled)
        thread.finished.connect(thread.deleteLater)

        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def cancel_async(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _on_worker_finished(self, result: BacktestResult) -> None:
        self.finished.emit(result)
        self._cleanup_worker()

    def _on_worker_failed(self, message: str) -> None:
        self.failed.emit(message)
        self._cleanup_worker()

    def _on_worker_cancelled(self) -> None:
        self.cancelled.emit()
        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
        if self._worker:
            self._worker.deleteLater()
        self._worker_thread = None
        self._worker = None

    # ------------------------------------------------------------------
    def _execute(
        self,
        request: BacktestRequest,
        db_path: Path,
        *,
        progress_callback: Optional[Callable[[str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> BacktestResult:
        universe = list(request.universe)
        start_date = request.start_date
        end_date = request.end_date

        price_cache: Dict[str, Dict[str, Dict[str, float]]] = {}
        collected_trades: List[Dict[str, Any]] = []

        def emit_progress(message: str) -> None:
            if progress_callback:
                progress_callback(message)

        def ensure_running() -> None:
            if cancel_callback and cancel_callback():
                raise BacktestCancelled()

        for idx, symbol in enumerate(universe):
            ensure_running()
            emit_progress(f"准备 {symbol} ({idx + 1}/{len(universe)}) 数据")
            candles, price_map = self._load_symbol_candles(db_path, symbol, start_date, end_date)
            if not candles:
                continue
            price_cache[symbol] = price_map
            context = StrategyContext(
                db_path=db_path,
                table_name=symbol,
                symbol=symbol,
                params=request.params,
                current_only=False,
                start_date=start_date,
                end_date=end_date,
                mode="backtest",
            )
            try:
                run_result = self.registry.run_strategy(request.strategy_key, context)
            except Exception as exc:  # pragma: no cover - runtime diagnostics
                self.progress.emit(f"{symbol} 回测失败: {exc}")
                continue

            trades = self._extract_trades(symbol, run_result, price_map, start_date, end_date)
            if trades:
                collected_trades.extend(trades)

        metrics: Dict[str, Any]
        equity_curve: List[Dict[str, Any]]
        trade_records: List[Dict[str, Any]]

        if not collected_trades:
            metrics = {
                "initial_cash": request.initial_cash,
                "final_equity": request.initial_cash,
                "net_profit": 0.0,
                "return_pct": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "trade_count": 0,
                "avg_pnl": 0.0,
                "skipped_trades": 0,
                "max_positions_used": 0,
            }
            equity_curve = [
                {
                    "date": (start_date or date.today()).isoformat(),
                    "equity": round(request.initial_cash, 2),
                }
            ]
            trade_records = []
            notes = "策略未返回可用交易，无法计算回测。"
        else:
            metrics, equity_curve, trade_records = self._simulate_portfolio(
                collected_trades,
                price_cache,
                request,
                cancel_callback=cancel_callback,
                progress_callback=progress_callback,
            )
            notes = f"处理 {len(collected_trades)} 条信号，成交 {metrics['trade_count']} 笔，跳过 {metrics['skipped_trades']} 笔。"

        return BacktestResult(
            strategy_key=request.strategy_key,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trade_records,
            notes=notes,
        )

    # ------------------------------------------------------------------
    def _simulate_portfolio(
        self,
        trades: List[Dict[str, Any]],
        price_cache: Dict[str, Dict[str, Dict[str, float]]],
        request: BacktestRequest,
        *,
        cancel_callback: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        valid_trades = [t for t in trades if t["entry_date"] < t["exit_date"]]
        valid_trades.sort(key=lambda t: (t["entry_date"], t["symbol"]))

        cash = request.initial_cash
        open_positions: List[Dict[str, Any]] = []
        trade_records: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []

        skip_count = 0
        wins = 0
        peak_equity = cash
        max_drawdown = 0.0
        max_positions_used = 0

        anchor_date = request.start_date or (valid_trades[0]["entry_date"] if valid_trades else date.today())
        equity_curve.append(
            {
                "date": anchor_date.isoformat(),
                "equity": round(cash, 2),
                "drawdown_pct": 0.0,
            }
        )

        commission = max(0.0, request.commission_rate)
        slippage = max(0.0, request.slippage)
        max_positions = max(1, request.max_positions)
        position_pct = min(1.0, max(0.0001, request.position_pct))

        def ensure_running() -> None:
            if cancel_callback and cancel_callback():
                raise BacktestCancelled()

        def emit_progress(message: str) -> None:
            if progress_callback:
                progress_callback(message)

        def portfolio_equity(at_date: date) -> float:
            value = cash
            for position in open_positions:
                mark = self._resolve_symbol_price(
                    position["symbol"],
                    at_date,
                    price_cache,
                    position["entry_price"],
                )
                value += position["shares"] * mark
            return value

        def record_equity(at_date: date) -> None:
            nonlocal peak_equity, max_drawdown
            equity = portfolio_equity(at_date)
            peak_equity = max(peak_equity, equity)
            drawdown_value = peak_equity - equity
            drawdown_pct = (drawdown_value / peak_equity * 100) if peak_equity else 0.0
            equity_curve.append(
                {
                    "date": at_date.isoformat(),
                    "equity": round(equity, 2),
                    "drawdown_pct": round(drawdown_pct, 2),
                }
            )
            max_drawdown = max(max_drawdown, drawdown_value)

        def close_position(position: Dict[str, Any]) -> None:
            ensure_running()
            nonlocal cash, wins
            symbol = position["symbol"]
            exit_date = position["exit_date"]
            exit_price = self._resolve_symbol_price(symbol, exit_date, price_cache, position["exit_price"])
            exit_fill = exit_price * (1.0 - slippage / 2)
            exit_value = position["shares"] * exit_fill
            exit_fee = exit_value * commission
            cash += exit_value - exit_fee

            pnl = exit_value - exit_fee - position["cost"]
            wins += 1 if pnl > 0 else 0
            trade_records.append(
                {
                    "symbol": symbol,
                    "entry_date": position["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry_price": round(position["entry_fill"], 4),
                    "exit_price": round(exit_fill, 4),
                    "shares": round(position["shares"], 4),
                    "pnl": round(pnl, 2),
                    "return_pct": round(pnl / position["cost"], 4) if position["cost"] else 0.0,
                    "holding_days": (exit_date - position["entry_date"]).days,
                    "note": position.get("note"),
                }
            )
            open_positions.remove(position)
            record_equity(exit_date)

        def close_positions_until(target_date: date) -> None:
            for position in list(open_positions):
                ensure_running()
                if position["exit_date"] <= target_date:
                    close_position(position)

        for trade in valid_trades:
            ensure_running()
            close_positions_until(trade["entry_date"])
            if len(open_positions) >= max_positions:
                skip_count += 1
                continue

            equity = portfolio_equity(trade["entry_date"])
            allocation = equity * position_pct
            available_cash = cash
            entry_price = trade["entry_price"]
            entry_fill = entry_price * (1.0 + slippage / 2)
            if entry_fill <= 0:
                skip_count += 1
                continue

            size_hint = trade.get("size_hint")
            if size_hint and size_hint > 0:
                shares = min(float(size_hint), available_cash / (entry_fill * (1 + commission)))
            else:
                allocation = min(allocation, available_cash)
                shares = allocation / entry_fill if entry_fill else 0.0

            if shares <= 0:
                skip_count += 1
                continue

            entry_value = shares * entry_fill
            entry_fee = entry_value * commission
            total_cost = entry_value + entry_fee
            if total_cost > cash:
                max_shares = cash / (entry_fill * (1 + commission))
                shares = max(0.0, max_shares)
                entry_value = shares * entry_fill
                entry_fee = entry_value * commission
                total_cost = entry_value + entry_fee

            if shares <= 0 or total_cost > cash:
                skip_count += 1
                continue

            cash -= total_cost
            position = {
                "symbol": trade["symbol"],
                "entry_date": trade["entry_date"],
                "exit_date": trade["exit_date"],
                "entry_price": trade["entry_price"],
                "exit_price": trade["exit_price"],
                "shares": shares,
                "entry_fill": entry_fill,
                "entry_value": entry_value,
                "entry_fee": entry_fee,
                "cost": total_cost,
                "note": trade.get("note"),
            }
            open_positions.append(position)
            open_positions.sort(key=lambda p: p["exit_date"])
            max_positions_used = max(max_positions_used, len(open_positions))
            record_equity(trade["entry_date"])
            emit_progress(f"持仓 {trade['symbol']} · {len(trade_records)} 笔成交")

        if open_positions:
            last_exit = max(pos["exit_date"] for pos in open_positions)
            close_positions_until(last_exit)

        final_equity = cash
        win_rate = wins / len(trade_records) if trade_records else 0.0
        avg_pnl = (sum(t["pnl"] for t in trade_records) / len(trade_records)) if trade_records else 0.0

        metrics = {
            "initial_cash": request.initial_cash,
            "final_equity": round(final_equity, 2),
            "net_profit": round(final_equity - request.initial_cash, 2),
            "return_pct": round((final_equity / request.initial_cash - 1) * 100, 2) if request.initial_cash else 0.0,
            "max_drawdown": round(max_drawdown, 2),
            "win_rate": win_rate,
            "trade_count": len(trade_records),
            "avg_pnl": round(avg_pnl, 2),
            "skipped_trades": skip_count,
            "max_positions_used": max_positions_used,
        }

        return metrics, equity_curve, trade_records

    # ------------------------------------------------------------------
    def _load_symbol_candles(
        self,
        db_path: Path,
        table_name: str,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, float]]]:
        payload = load_candles_from_sqlite(db_path, table_name)
        if not payload:
            return [], {}
        candles, _, _ = payload
        filtered: List[Dict[str, Any]] = []
        price_map: Dict[str, Dict[str, float]] = {}
        for candle in candles:
            candle_date = self._parse_date(candle.get("time"))
            if candle_date is None:
                continue
            if start_date and candle_date < start_date:
                continue
            if end_date and candle_date > end_date:
                continue
            key = candle_date.isoformat()
            price_map[key] = candle
            filtered.append(candle)
        return filtered, price_map

    def _extract_trades(
        self,
        symbol: str,
        run_result,
        price_map: Dict[str, Dict[str, float]],
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> List[Dict[str, Any]]:
        extra = getattr(run_result, "extra_data", {}) or {}
        raw_trades = list(extra.get("trades", []) or [])
        trades: List[Dict[str, Any]] = []

        for raw in raw_trades:
            entry_date = self._parse_date(raw.get("entry_time") or raw.get("entryTime"))
            exit_date = self._parse_date(raw.get("exit_time") or raw.get("exitTime"))
            if entry_date is None or exit_date is None:
                continue
            if start_date and entry_date < start_date:
                continue
            if end_date and exit_date > end_date:
                continue
            entry_price = self._safe_float(raw.get("entry_price") or raw.get("entryPrice"))
            if entry_price is None:
                entry_price = self._lookup_price(price_map, entry_date)
            exit_price = self._safe_float(raw.get("exit_price") or raw.get("exitPrice"))
            if exit_price is None:
                exit_price = self._lookup_price(price_map, exit_date)
            if entry_price is None or exit_price is None:
                continue
            trades.append(
                {
                    "symbol": symbol,
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "size_hint": self._safe_float(raw.get("size") or raw.get("shares") or raw.get("quantity")),
                    "note": raw.get("note") or raw.get("reason") or raw.get("entry_reason"),
                }
            )

        if trades:
            return trades

        # Fallback: attempt to pair buy/sell markers when trades are missing.
        markers = list(getattr(run_result, "markers", []) or [])
        return self._build_trades_from_markers(symbol, markers, price_map, start_date, end_date)

    def _build_trades_from_markers(
        self,
        symbol: str,
        markers: List[Dict[str, Any]],
        price_map: Dict[str, Dict[str, float]],
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> List[Dict[str, Any]]:
        trades: List[Dict[str, Any]] = []
        pending_buy: Optional[Tuple[date, float, Optional[str]]] = None
        sorted_markers = sorted(markers, key=lambda m: str(m.get("time", "")))
        for marker in sorted_markers:
            marker_date = self._parse_date(marker.get("time"))
            if marker_date is None:
                continue
            if start_date and marker_date < start_date:
                continue
            if end_date and marker_date > end_date:
                continue
            side = self._infer_marker_side(marker)
            price = self._safe_float(marker.get("price")) or self._lookup_price(price_map, marker_date)
            note = marker.get("text")
            if side == "buy" and price is not None:
                pending_buy = (marker_date, price, note)
            elif side == "sell" and price is not None and pending_buy:
                entry_date, entry_price, entry_note = pending_buy
                trades.append(
                    {
                        "symbol": symbol,
                        "entry_date": entry_date,
                        "exit_date": marker_date,
                        "entry_price": entry_price,
                        "exit_price": price,
                        "size_hint": None,
                        "note": entry_note or note,
                    }
                )
                pending_buy = None
        return trades

    # ------------------------------------------------------------------
    @staticmethod
    def _infer_marker_side(marker: Dict[str, Any]) -> Optional[str]:
        text = str(marker.get("text", "")).upper()
        position = str(marker.get("position", "")).lower()
        if "BUY" in text or position == "belowbar":
            return "buy"
        if "SELL" in text or position == "abovebar":
            return "sell"
        return None

    def _lookup_price(
        self,
        price_map: Dict[str, Dict[str, float]],
        target_date: date,
        field: str = "close",
        fallback: Optional[float] = None,
    ) -> Optional[float]:
        key = target_date.isoformat()
        candle = price_map.get(key)
        if candle and candle.get(field) is not None:
            return float(candle[field])
        for offset in range(1, 6):
            prev_key = (target_date - timedelta(days=offset)).isoformat()
            candle = price_map.get(prev_key)
            if candle and candle.get(field) is not None:
                return float(candle[field])
        return fallback

    def _resolve_symbol_price(
        self,
        symbol: str,
        target_date: date,
        price_cache: Dict[str, Dict[str, Dict[str, float]]],
        fallback: float,
    ) -> float:
        price_map = price_cache.get(symbol, {})
        price = self._lookup_price(price_map, target_date, fallback=fallback)
        return price if price is not None else fallback

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        text = str(value).strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(text[: len(fmt)], fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
