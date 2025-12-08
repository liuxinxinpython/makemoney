from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from PyQt5 import QtCore, QtWidgets  # type: ignore[import-not-found]
from PyQt5.QtWebEngineWidgets import QWebEngineView  # type: ignore[import-not-found]

try:
    from ..data.workers import CandleLoadWorker, SymbolLoadWorker  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - fallback when optional modules missing
    CandleLoadWorker = None
    SymbolLoadWorker = None

try:
    from ..rendering import TEMPLATE_PATH, build_mock_candles, load_maotai_candles, render_html  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - fallback defaults
    TEMPLATE_PATH = Path(__file__).parent.parent / "rendering" / "templates" / "tradingview_template.html"
    build_mock_candles = None
    load_maotai_candles = None
    render_html = None

try:
    from ..data.data_loader import load_candles_from_sqlite  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    load_candles_from_sqlite = None

try:
    from ..displays import DisplayManager  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional import
    DisplayManager = None

if TYPE_CHECKING:  # pragma: no cover
    from ..displays import DisplayManager as DisplayManagerType
else:  # pragma: no cover
    DisplayManagerType = Any


class SymbolFilterWorker(QtCore.QObject):
    """Background worker that filters large symbol datasets."""

    result_ready = QtCore.pyqtSignal(int, object, str)
    error = QtCore.pyqtSignal(int, str)

    @QtCore.pyqtSlot(int, object, str)
    def apply_filter(self, request_id: int, entries: object, query: str) -> None:
        try:
            dataset = list(entries or [])
            query_lower = (query or "").strip().lower()
            if not query_lower:
                filtered = dataset
            else:
                filtered: List[Dict[str, Any]] = []
                for entry in dataset:
                    if not isinstance(entry, dict):
                        continue
                    haystacks = [entry.get("symbol", ""), entry.get("name", ""), entry.get("table", "")]
                    haystacks = [str(value).lower() for value in haystacks if value]
                    if any(query_lower in text for text in haystacks):
                        filtered.append(entry)
            self.result_ready.emit(request_id, filtered, query_lower)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.error.emit(request_id, str(exc))


class KLineController(QtCore.QObject):
    """集中管理标的列表、K 线渲染和相关异步任务的控制器。"""

    symbol_changed = QtCore.pyqtSignal(str)
    symbols_updated = QtCore.pyqtSignal(list)
    filter_requested = QtCore.pyqtSignal(int, object, str)

    def __init__(
        self,
        *,
        web_view: QWebEngineView,
        loading_progress: QtWidgets.QProgressBar,
        status_bar: QtWidgets.QStatusBar,
        symbol_combo: QtWidgets.QComboBox,
        symbol_search: QtWidgets.QLineEdit,
        db_path_getter: Callable[[], Path],
        log_handler: Callable[[str], None],
            display_manager: Optional[DisplayManagerType] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.web_view = web_view
        self.loading_progress = loading_progress
        self.status_bar = status_bar
        self.symbol_combo = symbol_combo
        self.symbol_search = symbol_search
        self._db_path_getter = db_path_getter
        self._log = log_handler
        self.display_manager = display_manager

        self.symbol_entries: List[Dict[str, Any]] = []
        self.filtered_symbol_entries: List[Dict[str, Any]] = []
        self.current_symbol: Optional[str] = None
        self.current_symbol_name: str = ""
        self.current_table: Optional[str] = None
        self.current_markers: List[Dict[str, Any]] = []
        self.current_overlays: List[Dict[str, Any]] = []
        self.current_candles: List[Dict[str, Any]] = []
        self.current_volumes: List[Dict[str, Any]] = []
        self.current_instrument: Dict[str, Any] = {}

        self._symbol_load_thread: Optional[QtCore.QThread] = None
        self._symbol_loader: Optional[QtCore.QObject] = None
        self._candle_load_thread: Optional[QtCore.QThread] = None
        self._candle_loader: Optional[QtCore.QObject] = None
        self._filter_thread: Optional[QtCore.QThread] = None
        self._filter_worker: Optional[SymbolFilterWorker] = None
        self._filter_request_counter = 0
        self._latest_filter_result_id = 0
        self._filter_request_meta: Dict[int, Dict[str, Any]] = {}
        self.destroyed.connect(self._cleanup_filter_worker)

        self.symbol_combo.currentIndexChanged.connect(self._on_symbol_index_changed)
        self.symbol_search.textChanged.connect(self._on_search_text_changed)
        self.symbol_search.returnPressed.connect(self._activate_search_result)

    # ------------------------------------------------------------------
    # 基础属性
    # ------------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        value = self._db_path_getter()
        return value if isinstance(value, Path) else Path(value)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def load_initial_chart(self) -> None:
        self.loading_progress.setVisible(True)
        self.status_bar.showMessage("正在加载数据...")
        self.refresh_symbols_async()

        data_tuple = load_maotai_candles() if load_maotai_candles else None
        if not data_tuple and build_mock_candles:
            data_tuple = build_mock_candles()
            self._log("无法获取茅台数据，改用示例数据。")
        elif data_tuple:
            self._log("已加载茅台行情数据。")

        if data_tuple:
            candles, volumes, instrument = data_tuple
            self.current_table = None
            self.current_symbol = instrument.get("symbol") if instrument else None
            self.current_symbol_name = instrument.get("name") if instrument else ""
            self.current_markers = []
            self.current_overlays = []
            self._render_chart(candles, volumes, instrument, [], [])

        self.loading_progress.setVisible(False)
        self.status_bar.showMessage("数据加载完成")

    def refresh_symbols_async(self, select: Optional[str] = None) -> None:
        if SymbolLoadWorker is None:
            self.refresh_symbols(select=select)
            return

        self.loading_progress.setVisible(True)
        self.status_bar.showMessage("正在加载标的列表...")

        cached = self._read_symbols_cache()
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        if cached:
            self.symbol_entries = cached
            self.filtered_symbol_entries = cached.copy()
            for entry in cached:
                self.symbol_combo.addItem(entry.get("display", entry.get("symbol", "")), entry.get("table"))
            self.symbol_combo.setEnabled(True)
            self.symbol_combo.blockSignals(False)
            if select:
                self._select_in_combo(select)
            self.loading_progress.setVisible(False)
            self.status_bar.showMessage("就绪")
        else:
            self.symbol_combo.addItem("(加载中...)", None)
            self.symbol_combo.setEnabled(False)
            self.symbol_combo.blockSignals(False)
            self._log("没有缓存，开始后台加载标的列表")

        self._symbol_load_thread = QtCore.QThread(self)
        self._symbol_loader = SymbolLoadWorker(self.db_path)
        self._symbol_loader.moveToThread(self._symbol_load_thread)
        self._symbol_load_thread.started.connect(self._symbol_loader.run)
        self._symbol_loader.progress.connect(self._status_message)
        self._symbol_loader.failed.connect(self._on_symbol_load_failed)
        self._symbol_loader.finished.connect(lambda entries: self._on_symbol_load_finished(entries, select))
        self._symbol_loader.finished.connect(self._save_symbols_cache)
        self._symbol_load_thread.start()

    def refresh_symbols(self, select: Optional[str] = None) -> List[str]:
        self.symbol_entries = []
        self.filtered_symbol_entries = []
        db_path = self.db_path
        if not db_path.exists():
            self._reset_combo("(无数据)")
            return []

        symbol_names: List[str] = []
        try:
            with sqlite3.connect(db_path) as conn:  # type: ignore[attr-defined]
                rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
                for (table_name,) in rows:
                    table = str(table_name)
                    entry: Dict[str, Any] = {
                        "table": table,
                        "symbol": table.upper(),
                        "name": "",
                        "display": table.upper(),
                    }
                    try:
                        escaped = table.replace('"', '""')
                        meta = conn.execute(
                            f'SELECT symbol, name FROM "{escaped}" ORDER BY date DESC LIMIT 1'
                        ).fetchone()
                        if meta:
                            symbol_val = meta[0] if len(meta) > 0 else None
                            name_val = meta[1] if len(meta) > 1 else None
                            if isinstance(symbol_val, str) and symbol_val.strip():
                                entry["symbol"] = symbol_val.strip().upper()
                            elif symbol_val is not None:
                                entry["symbol"] = str(symbol_val).strip().upper()
                            if isinstance(name_val, str) and name_val.strip():
                                entry["name"] = name_val.strip()
                            elif name_val is not None:
                                entry["name"] = str(name_val).strip()
                    except Exception as exc:  # pragma: no cover - runtime diagnostics
                        self._log(f"读取 {table} 名称失败: {exc}")
                    entry["display"] = f"{entry['symbol']} · {entry['name']}" if entry["name"] else entry["symbol"]
                    self.symbol_entries.append(entry)
                    if entry["symbol"]:
                        symbol_names.append(entry["symbol"])
        except Exception as exc:  # pragma: no cover - runtime diagnostics
            self._log(f"加载标的列表失败: {exc}")

        if not self.symbol_entries:
            self._reset_combo("(无数据)")
            self.current_symbol = None
            self.current_table = None
            return []

        self.symbol_combo.setEnabled(True)
        self._apply_symbol_filter(select=select, maintain_selection=False)
        return symbol_names

    def focus_chart(self) -> None:
        try:
            self.web_view.setFocus()
        except Exception:
            pass

    def current_universe(self) -> List[str]:
        return [entry.get("table") for entry in self.symbol_entries if entry.get("table")]  # type: ignore[return-value]

    def select_symbol(self, table_name: str) -> None:
        if not table_name:
            return
        if self._select_in_list(table_name, self.filtered_symbol_entries):
            return
        if self.symbol_search.text():
            self.symbol_search.blockSignals(True)
            self.symbol_search.clear()
            self.symbol_search.blockSignals(False)
        self._apply_symbol_filter(select=table_name, maintain_selection=False)

    def set_markers(self, markers: List[Dict[str, Any]], overlays: List[Dict[str, Any]]) -> None:
        self.current_markers = list(markers)
        self.current_overlays = list(overlays)

    def render_from_database(
        self,
        table: str,
        markers: Optional[List[Dict[str, Any]]] = None,
        overlays: Optional[List[Dict[str, Any]]] = None,
        *,
        include_annotations: bool = False,
    ) -> None:
        if load_candles_from_sqlite is None:
            return
        data = load_candles_from_sqlite(self.db_path, table)
        if not data:
            return
        candles, volumes, instrument = data
        self._render_chart(
            candles,
            volumes,
            instrument,
            markers,
            overlays,
            include_annotations=include_annotations,
        )

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------
    def _on_symbol_load_failed(self, error_message: str) -> None:
        self._log(f"标的加载失败: {error_message}")
        self.loading_progress.setVisible(False)
        self.status_bar.showMessage("标的列表加载失败")

    def _on_symbol_load_finished(self, entries: List[Dict[str, Any]], select: Optional[str]) -> None:
        if self._symbol_load_thread:
            try:
                self._symbol_load_thread.quit()
                self._symbol_load_thread.wait(2000)
            except Exception:
                pass
            self._symbol_load_thread = None
            self._symbol_loader = None

        self.symbol_entries = entries
        self.filtered_symbol_entries = entries.copy()
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        for entry in entries:
            self.symbol_combo.addItem(entry.get("display", entry.get("symbol", "")), entry.get("table"))
        self.symbol_combo.setEnabled(True)
        self.symbol_combo.blockSignals(False)
        self._apply_symbol_filter(select=select, maintain_selection=False)
        self.loading_progress.setVisible(False)
        self.status_bar.showMessage("标的列表加载完成")

        chosen = self._find_entry(select) if select else (entries[0] if entries else None)
        if chosen and CandleLoadWorker:
            table_to_load = chosen.get("table")
            if table_to_load:
                self._start_candle_load_worker(table_to_load, chosen)

    def _on_candle_load_finished(self, data: object, chosen: Dict[str, Any]) -> None:
        if self._candle_load_thread:
            try:
                self._candle_load_thread.quit()
                self._candle_load_thread.wait(2000)
            except Exception:
                pass
            self._candle_load_thread = None
            self._candle_loader = None

        if data is None:
            symbol_label = chosen.get("symbol") or chosen.get("table") or "?"
            self._log(f"无法加载 {symbol_label} 的行情数据。")
            self.loading_progress.setVisible(False)
            self.status_bar.showMessage("数据加载失败")
            return

        try:
            candles, volumes, instrument = data
            self.current_table = chosen.get("table")
            self.current_symbol = instrument.get("symbol") or chosen.get("symbol")
            self.current_symbol_name = instrument.get("name") or chosen.get("name") or ""
            self.current_candles = list(candles) if candles else []
            self.current_volumes = list(volumes) if volumes else []
            self.current_instrument = instrument
            self.current_markers = []
            self.current_overlays = []
            self._render_chart(candles, volumes, instrument, [], [])
            if self.current_symbol:
                if self.current_symbol_name:
                    self.status_bar.showMessage(f"当前标的: {self.current_symbol} · {self.current_symbol_name}")
                else:
                    self.status_bar.showMessage(f"当前标的: {self.current_symbol}")
            self.symbol_changed.emit(self.current_table or "")
        finally:
            self.loading_progress.setVisible(False)

    def _on_symbol_index_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.filtered_symbol_entries):
            return
        entry = self.filtered_symbol_entries[index]
        table_name = entry.get("table")
        if not table_name or CandleLoadWorker is None:
            return
        if self._candle_load_thread:
            try:
                self._candle_load_thread.quit()
                self._candle_load_thread.wait(2000)
            except Exception:
                pass
            self._candle_load_thread = None
            self._candle_loader = None

        self.loading_progress.setVisible(True)
        self._log(f"启动后台加载 K 线数据: {entry.get('display')}")
        self.status_bar.showMessage(f"正在加载 {entry.get('display')} 的 K 线数据...")
        self._start_candle_load_worker(table_name, entry)

    def _on_search_text_changed(self, _text: str) -> None:
        self._apply_symbol_filter(maintain_selection=True)

    def _activate_search_result(self) -> None:
        if not self.filtered_symbol_entries:
            QtWidgets.QApplication.beep()
            return
        self.symbol_combo.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _status_message(self, message: str) -> None:
        self.status_bar.showMessage(message)

    def _start_candle_load_worker(self, table_name: str, chosen: Dict[str, Any]) -> None:
        self._candle_load_thread = QtCore.QThread(self)
        self._candle_loader = CandleLoadWorker(self.db_path, table_name)
        self._candle_loader.moveToThread(self._candle_load_thread)
        self._candle_load_thread.started.connect(self._candle_loader.run)
        self._candle_loader.finished.connect(lambda data, c=chosen: self._on_candle_load_finished(data, c))
        self._candle_loader.failed.connect(lambda e: self._log(f"加载 K 线失败: {e}"))
        self._candle_load_thread.start()

    def _ensure_filter_worker(self) -> None:
        if self._filter_worker is not None and self._filter_thread is not None:
            return
        thread = QtCore.QThread(self)
        worker = SymbolFilterWorker()
        worker.moveToThread(thread)
        worker.result_ready.connect(self._on_filter_result)
        worker.error.connect(self._on_filter_error)
        self.filter_requested.connect(worker.apply_filter)
        thread.start()
        self._filter_thread = thread
        self._filter_worker = worker

    def _cleanup_filter_worker(self, _obj: Optional[QtCore.QObject] = None) -> None:
        worker = self._filter_worker
        thread = self._filter_thread
        if worker:
            try:
                self.filter_requested.disconnect(worker.apply_filter)
            except Exception:
                pass
            try:
                worker.result_ready.disconnect(self._on_filter_result)
            except Exception:
                pass
            try:
                worker.error.disconnect(self._on_filter_error)
            except Exception:
                pass
            worker.deleteLater()
        if thread:
            thread.quit()
            thread.wait(2000)
            thread.deleteLater()
        self._filter_worker = None
        self._filter_thread = None

    def _on_filter_result(self, request_id: int, filtered_entries: object, query: str) -> None:
        meta = self._filter_request_meta.pop(request_id, None)
        if request_id < self._latest_filter_result_id:
            return
        self._latest_filter_result_id = request_id
        select = meta.get("select") if meta else None
        maintain = meta.get("maintain") if meta else False
        query_text = meta.get("query", query) if meta else query
        dataset = list(filtered_entries or [])
        self._update_filter_ui(dataset, select=select, maintain_selection=maintain, query=query_text)

    def _on_filter_error(self, request_id: int, message: str) -> None:
        meta = self._filter_request_meta.pop(request_id, None)
        self._log(f"过滤任务失败: {message}")
        if request_id < self._latest_filter_result_id:
            return
        dataset = self._filter_entries_local(self.symbol_entries, meta.get("query", "") if meta else "")
        select = meta.get("select") if meta else None
        maintain = meta.get("maintain") if meta else False
        self._latest_filter_result_id = request_id
        self._update_filter_ui(dataset, select=select, maintain_selection=maintain, query=meta.get("query", "") if meta else "")

    def _filter_entries_local(self, entries: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        query_lower = (query or "").strip().lower()
        if not query_lower:
            return list(entries)
        filtered: List[Dict[str, Any]] = []
        for entry in entries:
            haystacks = [entry.get("symbol", ""), entry.get("name", ""), entry.get("table", "")]
            haystacks = [str(value).lower() for value in haystacks if value]
            if any(query_lower in text for text in haystacks):
                filtered.append(entry)
        return filtered

    def _update_filter_ui(
        self,
        filtered_entries: List[Dict[str, Any]],
        *,
        select: Optional[str],
        maintain_selection: bool,
        query: str,
    ) -> None:
        self.filtered_symbol_entries = list(filtered_entries)
        self._log(
            f"过滤结果: query='{query}', 原始={len(self.symbol_entries)}, 保留={len(self.filtered_symbol_entries)}"
        )
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        if not self.filtered_symbol_entries:
            placeholder = "(无匹配)" if query else "(无数据)"
            self.symbol_combo.addItem(placeholder, None)
            self.symbol_combo.setEnabled(False)
            if not query:
                self.current_table = None
                self.current_symbol = None
                self.current_symbol_name = ""
                self.current_markers = []
            self.symbol_combo.blockSignals(False)
            self.symbols_updated.emit([])
            return

        self.symbol_combo.setEnabled(True)
        for entry in self.filtered_symbol_entries:
            label = entry.get("display") or entry.get("symbol") or entry.get("table") or ""
            self.symbol_combo.addItem(label)
            idx = self.symbol_combo.count() - 1
            self.symbol_combo.setItemData(idx, entry)

        identifier = select or (self.current_table if maintain_selection else None)
        target_index = 0
        if identifier:
            for idx, entry in enumerate(self.filtered_symbol_entries):
                if entry.get("table") == identifier or entry.get("symbol") == identifier:
                    target_index = idx
                    break

        previous_table = self.current_table
        self.symbol_combo.setCurrentIndex(target_index)
        self.symbol_combo.blockSignals(False)
        selected_entry = self.filtered_symbol_entries[target_index]
        if previous_table != selected_entry.get("table") or not maintain_selection:
            self._on_symbol_index_changed(target_index)
        self.symbols_updated.emit(list(self.filtered_symbol_entries))

    def _apply_symbol_filter(self, *, select: Optional[str] = None, maintain_selection: bool) -> None:
        query = self.symbol_search.text().strip().lower()
        entries_snapshot = list(self.symbol_entries)
        if not entries_snapshot:
            self._update_filter_ui([], select=select, maintain_selection=maintain_selection, query=query)
            return
        self._ensure_filter_worker()
        self._filter_request_counter += 1
        request_id = self._filter_request_counter
        self._filter_request_meta[request_id] = {
            "select": select,
            "maintain": maintain_selection,
            "query": query,
        }
        self.filter_requested.emit(request_id, entries_snapshot, query)

    def _reset_combo(self, placeholder: str) -> None:
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        self.symbol_combo.addItem(placeholder, None)
        self.symbol_combo.setEnabled(False)
        self.symbol_combo.blockSignals(False)
        self.symbols_updated.emit([])

    def _select_in_list(self, target: str, entries: List[Dict[str, Any]]) -> bool:
        for idx, entry in enumerate(entries):
            if entry.get("table") == target or entry.get("symbol") == target:
                self.symbol_combo.setCurrentIndex(idx)
                return True
        return False

    def _select_in_combo(self, target: str) -> None:
        for idx, entry in enumerate(self.symbol_entries):
            if entry.get("table") == target or entry.get("symbol") == target:
                self.symbol_combo.setCurrentIndex(idx)
                break

    def _find_entry(self, table_or_symbol: Optional[str]) -> Optional[Dict[str, Any]]:
        if not table_or_symbol:
            return None
        for entry in self.symbol_entries:
            if entry.get("table") == table_or_symbol or entry.get("symbol") == table_or_symbol:
                return entry
        return None

    def _render_chart(
        self,
        candles: List[Dict[str, float]],
        volumes: List[Dict[str, float]],
        instrument: Optional[Dict[str, str]] = None,
        markers: Optional[List[Dict[str, Any]]] = None,
        overlays: Optional[List[Dict[str, Any]]] = None,
        *,
        include_annotations: bool = False,
    ) -> None:
        self.current_candles = list(candles) if candles else []
        if include_annotations:
            if markers is not None:
                current_markers = markers
            elif self.display_manager:
                current_markers = self.display_manager.get_current_markers()
            else:
                current_markers = self.current_markers

            if overlays is not None:
                current_overlays = overlays
            elif self.display_manager:
                current_overlays = self.display_manager.get_current_overlays()
            else:
                current_overlays = self.current_overlays
        else:
            # Keep main TradingView chart clean; strategy previews live in the ECharts dialog.
            current_markers = []
            current_overlays = []

        if render_html is None:
            return
        html = render_html(candles, volumes, instrument, current_markers, current_overlays)
        base_url = QtCore.QUrl.fromLocalFile(str(TEMPLATE_PATH))
        self.web_view.setHtml(html, base_url)

    def _save_symbols_cache(self, entries: List[Dict[str, Any]]) -> None:
        try:
            cache_file = Path(str(self.db_path) + ".symbols.json")
            cache_file.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _read_symbols_cache(self) -> Optional[List[Dict[str, Any]]]:
        cache_file = Path(str(self.db_path) + ".symbols.json")
        if not cache_file.exists():
            return None
        try:
            raw = cache_file.read_text(encoding="utf-8")
            cached = json.loads(raw)
            if isinstance(cached, list):
                if not all(isinstance(entry, dict) for entry in cached):
                    return None
                requires_refresh = any(
                    "last_price" not in entry or "change_percent" not in entry
                    for entry in cached
                )
                if requires_refresh:
                    self._log("缓存缺少最新行情字段，将重新加载数据库。")
                    return None
                self._log(f"从缓存加载了 {len(cached)} 条标的记录")
                return cached  # type: ignore[return-value]
        except Exception as exc:
            self._log(f"缓存加载失败: {exc}")
        return None


__all__ = ["KLineController"]
