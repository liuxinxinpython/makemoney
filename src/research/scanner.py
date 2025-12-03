from __future__ import annotations

import random
from typing import List

from PyQt5 import QtCore  # type: ignore[import-not-found]

from .models import ScanRequest, ScanResult, StrategyContext
from .strategy_registry import StrategyRegistry


class StrategyScanner(QtCore.QObject):
    """Batch runner that evaluates a strategy across a universe."""

    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, registry: StrategyRegistry, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.registry = registry

    def run(self, request: ScanRequest, db_path) -> List[ScanResult]:  # sync helper for now
        try:
            results = self._execute(request, db_path)
            self.finished.emit(results)
            return results
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))
            raise

    # ------------------------------------------------------------------
    def _execute(self, request: ScanRequest, db_path) -> List[ScanResult]:
        scan_results: List[ScanResult] = []
        for idx, table_name in enumerate(request.universe):
            self.progress.emit(f"扫描 {table_name} ({idx + 1}/{len(request.universe)})")
            context = StrategyContext(
                db_path=db_path,
                table_name=table_name,
                symbol=table_name,
                params=request.params,
                current_only=False,
            )
            run_result = self.registry.run_strategy(request.strategy_key, context)
            score = len(run_result.markers)
            scan_results.append(
                ScanResult(
                    strategy_key=request.strategy_key,
                    symbol=context.symbol or table_name,
                    table_name=table_name,
                    score=score,
                    signals=run_result.markers[:10],
                    metadata={"status": run_result.status_message or ""},
                )
            )
        # Simple ranking by score desc
        scan_results.sort(key=lambda r: r.score, reverse=True)
        return scan_results
