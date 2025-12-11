from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from PyQt5 import QtCore  # type: ignore[import-not-found]

from ..data.bulk_loader import load_candles_bulk
from ..data.data_loader import discard_preloaded_tables, inject_preloaded_candles
from .models import ScanRequest, ScanResult, StrategyContext
from .strategy_registry import StrategyRegistry


class ScanCancelled(RuntimeError):
    """Raised when a scan task is cancelled mid-way."""


class StrategyScanWorker(QtCore.QObject):
    """Background worker that executes a stock-picking scan in a QThread."""

    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    cancelled = QtCore.pyqtSignal()

    def __init__(self, scanner: "StrategyScanner", request: ScanRequest, db_path) -> None:
        super().__init__()
        self._scanner = scanner
        self._request = request
        self._db_path = db_path
        self._cancelled = False

    def run(self) -> None:
        try:
            results = self._scanner._execute(
                self._request,
                self._db_path,
                progress_callback=self.progress.emit,
                cancel_callback=lambda: self._cancelled,
            )
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:  # pragma: no cover - background diagnostics
            self.failed.emit(str(exc))
        else:
            self.finished.emit(results)

    def cancel(self) -> None:
        self._cancelled = True


class StrategyScanner(QtCore.QObject):
    """Batch runner that evaluates a strategy across a universe."""

    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    cancelled = QtCore.pyqtSignal()

    def __init__(
        self,
        registry: StrategyRegistry,
        parent: QtCore.QObject | None = None,
        *,
        batch_size: int = 32,
        max_workers: Optional[int] = None,
        rows_per_symbol: Optional[int] = 1500,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self._worker_thread: Optional[QtCore.QThread] = None
        self._worker: Optional[StrategyScanWorker] = None
        self.batch_size = max(1, batch_size)
        cpu_default = os.cpu_count() or 4
        self.max_workers = max(1, max_workers or min(32, cpu_default * 4))
        self.rows_per_symbol = rows_per_symbol

    def run(self, request: ScanRequest, db_path) -> List[ScanResult]:
        try:
            results = self._execute(request, db_path, progress_callback=self.progress.emit)
            self.finished.emit(results)
            return results
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))
            raise

    def run_async(self, request: ScanRequest, db_path) -> None:
        if self._worker_thread is not None:
            raise RuntimeError("扫描任务仍在运行，无法重复启动。")

        thread = QtCore.QThread()
        worker = StrategyScanWorker(self, request, db_path)
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

    # ------------------------------------------------------------------
    def _on_worker_finished(self, results: object) -> None:
        self.finished.emit(results)
        self._cleanup_worker()

    def _on_worker_failed(self, message: str) -> None:
        self.failed.emit(message)
        self._cleanup_worker()

    def _on_worker_cancelled(self) -> None:
        self.progress.emit("扫描已取消")
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
        request: ScanRequest,
        db_path,
        *,
        progress_callback: Optional[Callable[[str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> List[ScanResult]:
        db_path_obj = Path(db_path)
        universe = list(request.universe)
        total = len(universe)
        if total == 0:
            return []

        scan_results: List[ScanResult] = []
        processed = 0
        chunked_universe = list(self._chunk(universe, self.batch_size))
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for batch_index, batch in enumerate(chunked_universe):
                if cancel_callback and cancel_callback():
                    raise ScanCancelled()
                preloaded = load_candles_bulk(
                    db_path_obj,
                    batch,
                    limit_per_table=self.rows_per_symbol,
                    start_date=request.start_date,
                    end_date=request.end_date,
                )
                for table_name, payload in preloaded.items():
                    inject_preloaded_candles(db_path_obj, table_name, payload)

                futures = {
                    executor.submit(
                        self._evaluate_symbol,
                        table_name,
                        request,
                        db_path_obj,
                        cancel_callback,
                    ): table_name
                    for table_name in batch
                }

                for future in as_completed(futures):
                    table_name = futures[future]
                    processed += 1
                    try:
                        result = future.result()
                    except ScanCancelled:
                        raise
                    except Exception as exc:
                        if progress_callback:
                            progress_callback(f"{table_name} 扫描失败: {exc}")
                    else:
                        if result is not None:
                            scan_results.append(result)
                    if progress_callback:
                        progress_callback(f"扫描 {table_name} ({processed}/{total})")
                    if cancel_callback and cancel_callback():
                        raise ScanCancelled()

                discard_preloaded_tables(db_path_obj, batch)

        scan_results.sort(key=lambda r: r.score, reverse=True)
        return scan_results

    def _evaluate_symbol(
        self,
        table_name: str,
        request: ScanRequest,
        db_path: Path,
        cancel_callback: Optional[Callable[[], bool]],
    ) -> Optional[ScanResult]:
        if cancel_callback and cancel_callback():
            raise ScanCancelled()
        context = StrategyContext(
            db_path=db_path,
            table_name=table_name,
            symbol=table_name,
            params=request.params,
            current_only=False,
            start_date=request.start_date,
            end_date=request.end_date,
            mode="scan",
        )
        run_result = self.registry.run_strategy(request.strategy_key, context)
        result_payload = self._build_scan_payload(
            run_result,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        if result_payload is None:
            return None
        return ScanResult(
            strategy_key=request.strategy_key,
            symbol=context.symbol or table_name,
            table_name=table_name,
            score=result_payload["score"],
            entry_date=result_payload["entry_date"],
            entry_price=result_payload["entry_price"],
            confidence=result_payload["confidence"],
            signals=result_payload["candidates"],
            extra_signals=result_payload["signals"],
            metadata=result_payload["metadata"],
        )

    def _build_scan_payload(
        self,
        run_result,
        *,
        start_date,
        end_date,
    ) -> Optional[Dict[str, Any]]:
        markers = list(getattr(run_result, "markers", []) or [])
        candidates = self._collect_candidates(run_result, start_date, end_date)
        if not candidates and not self._contains_buy_signal(run_result, markers, start_date, end_date):
            return None

        primary = candidates[0] if candidates else self._fallback_candidate(markers, start_date, end_date)
        if primary is None:
            return None

        score = float(primary.get("score") or primary.get("confidence") or len(markers))
        entry_date = primary.get("date") or primary.get("time")
        entry_price = primary.get("price") or primary.get("close")
        confidence = primary.get("confidence") or primary.get("score")
        note = primary.get("note") or primary.get("label")

        metadata = {"status": run_result.status_message or ""}
        if note:
            metadata["note"] = str(note)

        return {
            "score": score,
            "entry_date": entry_date,
            "entry_price": float(entry_price) if self._is_number(entry_price) else None,
            "confidence": float(confidence) if self._is_number(confidence) else None,
            "candidates": candidates[:5],
            "signals": markers[:10],
            "metadata": metadata,
        }

    def _collect_candidates(self, run_result, start_date, end_date) -> List[Dict[str, Any]]:
        extra = getattr(run_result, "extra_data", {}) or {}
        raw = extra.get("scan_candidates")
        if not isinstance(raw, list):
            return []
        candidates: List[Dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            candidate_date = self._coerce_date(row.get("date") or row.get("time"))
            if candidate_date and not self._in_date_range(candidate_date, start_date, end_date):
                continue
            candidates.append(row)
        candidates.sort(key=lambda item: item.get("score") or item.get("confidence") or 0, reverse=True)
        return candidates

    def _fallback_candidate(
        self,
        markers: List[Dict[str, Any]],
        start_date,
        end_date,
    ) -> Optional[Dict[str, Any]]:
        if not markers:
            return None
        # Pick the latest buy-like marker to avoid误选非买点信号
        for marker in reversed(markers):
            text = str(marker.get("text") or marker.get("label") or "").upper()
            if "BUY" in text or "买" in text:
                marker_date = self._coerce_date(marker.get("time") or marker.get("date"))
                if marker_date and not self._in_date_range(marker_date, start_date, end_date):
                    continue
                return {
                    "date": marker.get("time") or marker.get("date"),
                    "price": marker.get("price") or marker.get("close"),
                    "score": marker.get("score") or 1,
                    "note": marker.get("text") or marker.get("label"),
                }
        return None

    def _contains_buy_signal(self, run_result, markers: List[Dict[str, Any]], start_date, end_date) -> bool:
        for marker in markers:
            text = str(marker.get("text") or marker.get("label") or "").upper()
            if "BUY" in text or "买" in text:
                marker_date = self._coerce_date(marker.get("time") or marker.get("date"))
                if marker_date and not self._in_date_range(marker_date, start_date, end_date):
                    continue
                return True
        extra = getattr(run_result, "extra_data", {}) or {}
        trades = extra.get("trades") or []
        if isinstance(trades, list):
            for trade in trades:
                if not isinstance(trade, dict):
                    continue
                entry_time = trade.get("entry_time") or trade.get("entryTime")
                trade_date = self._coerce_date(entry_time)
                if trade_date and not self._in_date_range(trade_date, start_date, end_date):
                    continue
                if entry_time or trade.get("entry_price") or trade.get("entryPrice"):
                    return True
        candidates = extra.get("scan_candidates")
        if isinstance(candidates, list):
            for row in candidates:
                if not isinstance(row, dict):
                    continue
                candidate_date = self._coerce_date(row.get("date") or row.get("time"))
                if candidate_date and not self._in_date_range(candidate_date, start_date, end_date):
                    continue
                return True
        return False

    def _coerce_date(self, value):
        """Convert various date representations to date object; return None if unknown."""
        try:
            from datetime import datetime, date
        except Exception:
            return True
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value).date()
            except Exception:
                return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text[:19]).date()
            except Exception:
                pass
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date()
            except Exception:
                return None
        return None

    @staticmethod
    def _in_date_range(candidate_date, start_date, end_date) -> bool:
        if candidate_date is None:
            return False
        if start_date and candidate_date < start_date:
            return False
        if end_date and candidate_date > end_date:
            return False
        return True

    @staticmethod
    def _is_number(value: Any) -> bool:
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _chunk(items: List[str], size: int) -> Iterable[List[str]]:
        if size <= 0:
            size = 1
        for idx in range(0, len(items), size):
            yield items[idx : idx + size]
