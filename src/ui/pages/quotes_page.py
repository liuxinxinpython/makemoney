from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, List, Tuple

from PyQt5 import QtCore, QtWidgets
from ..controllers.symbol_list_manager import SymbolListManager

if TYPE_CHECKING:  # pragma: no cover
    from ...main_ui import MainWindow


class SnowQuotesPage(QtWidgets.QWidget):
    """Encapsulates the Snow盈风格行情主界面布局。"""

    def __init__(self, *, host: "MainWindow", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._host = host

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.body_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self.body_splitter.setChildrenCollapsible(False)
        layout.addWidget(self.body_splitter, 1)

        self.stock_panel = self._create_stock_panel(self.body_splitter)
        self.body_splitter.addWidget(self.stock_panel)

        self.chart_panel = self._create_chart_panel(self.body_splitter)
        self.body_splitter.addWidget(self.chart_panel)

        self.strategy_sidebar = self._create_strategy_sidebar(self.body_splitter)
        self.body_splitter.addWidget(self.strategy_sidebar)
        if self.strategy_sidebar:
            self.strategy_sidebar.setVisible(False)

        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        self.body_splitter.setStretchFactor(2, 0)

        self._bind_host()

    def _bind_host(self) -> None:
        host = self._host
        host.body_splitter = self.body_splitter
        host.stock_panel = self.stock_panel
        host.chart_panel = self.chart_panel
        host.strategy_sidebar = self.strategy_sidebar

    def _create_stock_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame(parent)
        panel.setObjectName("snowStockPanel")
        panel.setMinimumWidth(280)
        panel.setStyleSheet(
            """
QFrame#snowStockPanel {
    background: #ffffff;
    border-radius: 0;
}
"""
        )
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("股票列表", panel)
        header.setObjectName("snowStockHeader")
        layout.addWidget(header)

        tabs_container = QtWidgets.QFrame(panel)
        tabs_container.setObjectName("snowSymbolTabsContainer")
        tabs_container.setStyleSheet(
            """
QFrame#snowSymbolTabsContainer {
    background: #ffffff;
    border-top: 1px solid #e5e8f1;
    border-bottom: 1px solid #e5e8f1;
}
"""
        )
        tabs_layout = QtWidgets.QVBoxLayout(tabs_container)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(10)

        category_bar = QtWidgets.QTabBar(tabs_container)
        category_bar.setObjectName("snowCategoryTabs")
        category_bar.setDrawBase(False)
        category_bar.setExpanding(False)
        category_bar.setUsesScrollButtons(False)
        category_bar.setElideMode(QtCore.Qt.ElideRight)
        category_bar.setFocusPolicy(QtCore.Qt.NoFocus)
        for label in ("全部", "自选"):
            category_bar.addTab(label)
        category_bar.setCurrentIndex(0)
        category_bar.setStyleSheet(
            """
QTabBar#snowCategoryTabs {
    background: transparent;
    qproperty-drawBase: 0;
    padding-left: 6px;
    border-bottom: 1px solid #e5e8f1;
}
QTabBar#snowCategoryTabs::tab {
    color: #6f7b95;
    padding: 4px 0;
    margin-right: 26px;
    font-size: 15px;
    font-weight: 500;
    border-bottom: 3px solid transparent;
    background: transparent;
}
QTabBar#snowCategoryTabs::tab:selected {
    color: #1f6dff;
    font-weight: 600;
}
QTabBar#snowCategoryTabs::tab:hover {
    color: #1f6dff;
}
"""
        )
        tabs_layout.addWidget(category_bar)
        self._host.symbol_tabs = category_bar


        stack = QtWidgets.QStackedWidget(tabs_container)
        tabs_layout.addWidget(stack, 1)

        all_tab = QtWidgets.QWidget(stack)
        all_layout = QtWidgets.QVBoxLayout(all_tab)
        all_layout.setContentsMargins(0, 0, 0, 0)
        all_layout.setSpacing(6)
        all_layout.addWidget(self._create_symbol_list_header(all_tab))
        all_list = QtWidgets.QListView(all_tab)
        all_list.setObjectName("snowAllSymbols")
        all_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        all_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        all_list.setSelectionRectVisible(True)
        all_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        all_list.setSpacing(2)
        all_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        all_list.customContextMenuRequested.connect(self._show_all_list_menu)
        all_layout.addWidget(all_list, 1)
        stack.addWidget(all_tab)
        self._host.all_symbol_list = all_list

        fav_tab = QtWidgets.QWidget(stack)
        fav_layout = QtWidgets.QVBoxLayout(fav_tab)
        fav_layout.setContentsMargins(0, 0, 0, 0)
        fav_layout.setSpacing(6)

        tabs_row = QtWidgets.QHBoxLayout()
        tabs_row.setContentsMargins(8, 0, 8, 0)
        tabs_row.setSpacing(6)
        watchlist_tabs = QtWidgets.QTabBar(fav_tab)
        watchlist_tabs.setObjectName("snowWatchlistTabs")
        watchlist_tabs.setDrawBase(False)
        watchlist_tabs.setExpanding(False)
        watchlist_tabs.setUsesScrollButtons(True)
        watchlist_tabs.setElideMode(QtCore.Qt.ElideRight)
        watchlist_tabs.setFocusPolicy(QtCore.Qt.NoFocus)
        watchlist_tabs.currentChanged.connect(self._on_watchlist_tab_changed)
        watchlist_tabs.setStyleSheet(
            """
QTabBar#snowWatchlistTabs {
    background: transparent;
    padding-left: 4px;
}
QTabBar#snowWatchlistTabs::tab {
    color: #6f7b95;
    padding: 2px 6px;
    margin-right: 10px;
    font-size: 13px;
    border: none;
    background: transparent;
}
QTabBar#snowWatchlistTabs::tab:selected {
    color: #1f6dff;
    font-weight: 600;
}
QTabBar#snowWatchlistTabs::tab:hover {
    color: #1f6dff;
}
"""
        )
        tabs_row.addWidget(watchlist_tabs, 1)
        manage_btn = QtWidgets.QToolButton(fav_tab)
        manage_btn.setText("…")
        manage_btn.setToolTip("管理/新建分组")
        manage_btn.clicked.connect(self._open_watchlist_manager)
        tabs_row.addWidget(manage_btn)
        fav_layout.addLayout(tabs_row)

        fav_layout.addWidget(self._create_symbol_list_header(fav_tab))

        fav_list = QtWidgets.QListView(fav_tab)
        fav_list.setObjectName("snowFavoriteSymbols")
        fav_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        fav_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        fav_list.setSelectionRectVisible(True)
        fav_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        fav_list.setSpacing(2)
        fav_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        fav_list.customContextMenuRequested.connect(self._show_watchlist_menu)
        fav_layout.addWidget(fav_list, 1)
        stack.addWidget(fav_tab)
        self._host.favorite_symbol_list = fav_list
        self._watchlist_tabs = watchlist_tabs
        self._watchlist_view = fav_list
        self._favorite_manager: Optional[SymbolListManager] = None

        category_bar.currentChanged.connect(stack.setCurrentIndex)
        category_bar.currentChanged.connect(self._on_category_changed)
        # 行情页显示市场标签，自选页不需要隐藏它们以保持布局稳定
        stack.setCurrentIndex(category_bar.currentIndex())

        QtCore.QTimer.singleShot(0, self._init_watchlists)

        layout.addWidget(tabs_container, 1)

        QtCore.QTimer.singleShot(0, self._host._ensure_sample_symbols)

        return panel

    def _create_symbol_list_header(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        header = QtWidgets.QFrame(parent)
        header.setObjectName("snowSymbolListHeader")
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)

        name_label = QtWidgets.QLabel("名称/代码", header)
        name_label.setObjectName("snowSymbolHeaderName")
        layout.addWidget(name_label, 1)

        price_label = QtWidgets.QLabel("最新价", header)
        price_label.setObjectName("snowSymbolHeaderPrice")
        price_label.setAlignment(QtCore.Qt.AlignCenter)
        price_label.setFixedWidth(72)
        layout.addWidget(price_label)

        change_label = QtWidgets.QLabel("涨跌幅", header)
        change_label.setObjectName("snowSymbolHeaderChange")
        change_label.setAlignment(QtCore.Qt.AlignCenter)
        change_label.setFixedWidth(72)
        layout.addWidget(change_label)

        return header

    def _create_watchlist_header(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        header = QtWidgets.QFrame(parent)
        header.setObjectName("snowWatchlistHeader")
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(4)

        name_label = QtWidgets.QLabel("名称", header)
        name_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addWidget(name_label, 1)

        code_label = QtWidgets.QLabel("代码", header)
        code_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        code_label.setFixedWidth(96)
        layout.addWidget(code_label)
        return header

    def _create_chart_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame(parent)
        panel.setObjectName("snowChartPanel")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        if self._host.loading_progress is not None:
            layout.addWidget(self._host.loading_progress)
        layout.addWidget(self._host.web_view, 1)
        return panel

    def _create_strategy_sidebar(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        sidebar = QtWidgets.QFrame(parent)
        sidebar.setObjectName("snowStrategySidebar")
        sidebar.setMinimumWidth(360)
        layout = QtWidgets.QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        title = QtWidgets.QLabel("策略工作台", sidebar)
        title.setObjectName("snowStrategyHeader")
        header_row.addWidget(title)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        container = QtWidgets.QFrame(sidebar)
        container.setObjectName("snowStrategyContainer")
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        placeholder = QtWidgets.QLabel("正在初始化策略工作台...", container)
        placeholder.setObjectName("snowStrategyPlaceholder")
        placeholder.setAlignment(QtCore.Qt.AlignCenter)
        container_layout.addWidget(placeholder, 1)
        layout.addWidget(container, 1)

        self._host.strategy_panel_container = container
        self._host.strategy_panel_layout = container_layout
        self._host.strategy_placeholder_label = placeholder
        return sidebar

    # --- Watchlist management -----------------------------------------
    def _selected_watchlist_items(self) -> List[Dict[str, Any]]:
        """Return selected entries from the watchlist view."""
        view = getattr(self, "_watchlist_view", None)
        if view is None:
            return []
        selection = view.selectedIndexes()
        entries: List[Dict[str, Any]] = []
        for idx in selection:
            entry = idx.data(QtCore.Qt.UserRole + 1)
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _lookup_symbol_meta(self, symbol: str) -> Dict[str, Any]:
        """Find cached latest价/涨跌幅数据 from the main symbol list."""
        kc = getattr(self._host, "kline_controller", None)
        if kc is None:
            return {}
        target = (symbol or "").strip().upper()
        for entry in getattr(kc, "symbol_entries", []):
            entry_symbol = str(entry.get("symbol") or entry.get("table") or "").upper()
            if entry_symbol == target:
                return entry
        return {}

    def _selected_all_items(self) -> List[Dict[str, Any]]:
        """Return selected entries from the '全部'列表."""
        view = getattr(self._host, "all_symbol_list", None)
        if view is None:
            return []
        selection = view.selectedIndexes()
        entries: List[Dict[str, Any]] = []
        for idx in selection:
            entry = idx.data(QtCore.Qt.UserRole + 1)
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _show_all_list_menu(self, pos: QtCore.QPoint) -> None:
        view = getattr(self._host, "all_symbol_list", None)
        store = getattr(self._host, "watchlist_store", None)
        if view is None or store is None:
            return
        index = view.indexAt(pos)
        if index.isValid():
            selection_model = view.selectionModel()
            if selection_model:
                selection_model.select(index, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        entries = self._selected_all_items()
        if not entries:
            return

        try:
            groups = store.list_watchlists()
        except Exception:
            groups = []
        if not groups:
            QtWidgets.QMessageBox.information(self, "缺少分组", "请先在自选页创建分组后再添加股票。")
            return

        menu = self._styled_menu(view)
        add_menu = menu.addMenu("加入自选分组")
        for wid, name in groups:
            action = add_menu.addAction(str(name))
            action.triggered.connect(lambda _checked=False, gid=int(wid): self._add_selected_all_to_watchlist(gid))
        manage_action = menu.addAction("管理/新建分组...")
        manage_action.triggered.connect(self._open_watchlist_manager)
        menu.exec_(view.viewport().mapToGlobal(pos))

    def _add_selected_all_to_watchlist(self, target_id: Optional[int]) -> None:
        entries = self._selected_all_items()
        if not entries:
            QtWidgets.QMessageBox.information(self, "未选择", "请先选择要加入自选的股票。")
            return
        if target_id is None:
            QtWidgets.QMessageBox.information(self, "缺少分组", "请先选择要加入的自选分组。")
            return
        items: List[Tuple[str, str]] = []
        for entry in entries:
            sym = entry.get("symbol") or entry.get("table")
            name = entry.get("name") or entry.get("display") or sym
            if sym:
                items.append((str(sym), str(name or sym)))
        if not items:
            QtWidgets.QMessageBox.information(self, "无有效数据", "所选条目缺少代码，无法加入自选。")
            return
        try:
            self._host.add_symbols_to_watchlist(items, watchlist_id=int(target_id))
            # Switch tab to the target group after adding for immediate feedback
            tabs = getattr(self, "_watchlist_tabs", None)
            if tabs:
                idx = next((i for i in range(tabs.count()) if tabs.tabData(i) == int(target_id)), -1)
                if idx >= 0:
                    tabs.blockSignals(True)
                    tabs.setCurrentIndex(idx)
                    tabs.blockSignals(False)
            self._host.current_watchlist_id = int(target_id)
            self.refresh_watchlist_view(int(target_id))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "加入自选失败", str(exc))

    def _styled_menu(self, parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(parent)
        menu.setStyleSheet(
            """
            QMenu {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                padding: 6px 4px;
                border-radius: 8px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: #e6f0ff;
                color: #0f172a;
            }
            QMenu::separator {
                height: 1px;
                margin: 4px 8px;
                background: #e2e8f0;
            }
            """
        )
        return menu

    def _on_category_changed(self, index: int) -> None:
        if index == 1:
            self.refresh_watchlist_view()

    def _init_watchlists(self) -> None:
        tabs = getattr(self, "_watchlist_tabs", None)
        store = getattr(self._host, "watchlist_store", None)
        if tabs is None or store is None:
            return
        if self._favorite_manager is None and self._watchlist_view is not None:
            self._favorite_manager = SymbolListManager(
                list_view=self._watchlist_view,
                select_symbol=self._host._select_symbol_from_manager if hasattr(self._host, "_select_symbol_from_manager") else None,
                current_table_getter=self._host._current_symbol_table if hasattr(self._host, "_current_symbol_table") else None,
                log_handler=self._host.append_log if hasattr(self._host, "append_log") else None,
                selection_mode=QtWidgets.QAbstractItemView.ExtendedSelection,
            )
        lists = self._load_watchlists(store)
        tabs.blockSignals(True)
        while tabs.count():
            tabs.removeTab(0)
        for wid, name in lists:
            tabs.addTab(str(name))
            tabs.setTabData(tabs.count() - 1, int(wid))
        tabs.blockSignals(False)
        if not lists:
            self._host.current_watchlist_id = None
            self.refresh_watchlist_view()
            return

        target_id: Optional[int] = (
            int(self._host.current_watchlist_id) if self._host.current_watchlist_id else None
        )
        if target_id is None:
            target_id = int(lists[0][0])

        idx = next((i for i in range(tabs.count()) if tabs.tabData(i) == int(target_id)), -1)
        if idx >= 0:
            tabs.setCurrentIndex(idx)
            self._host.current_watchlist_id = int(target_id)
        else:
            tabs.setCurrentIndex(0)
            self._host.current_watchlist_id = int(tabs.tabData(0))
        self.refresh_watchlist_view()

    def _load_watchlists(self, store: Any) -> List[tuple]:
        try:
            return store.list_watchlists()
        except Exception:
            return []

    def _on_watchlist_tab_changed(self, index: int) -> None:
        tabs = getattr(self, "_watchlist_tabs", None)
        if tabs is None:
            return
        wid = tabs.tabData(index)
        self._host.current_watchlist_id = int(wid) if wid else None
        self.refresh_watchlist_view()

    def refresh_watchlist_view(self, watchlist_id: Optional[int] = None) -> None:
        view = getattr(self, "_watchlist_view", None)
        store = getattr(self._host, "watchlist_store", None)
        manager = getattr(self, "_favorite_manager", None)
        if view is None or store is None or manager is None:
            return
        wid = watchlist_id or self._host.current_watchlist_id
        if not wid:
            manager.populate([], is_sample=False)
            return
        tabs = getattr(self, "_watchlist_tabs", None)
        if tabs and wid:
            idx = next((i for i in range(tabs.count()) if tabs.tabData(i) == int(wid)), -1)
            if idx >= 0:
                tabs.blockSignals(True)
                tabs.setCurrentIndex(idx)
                tabs.blockSignals(False)
        try:
            symbols = store.list_symbols(int(wid)) if wid else []
        except Exception:
            symbols = []
        entries: List[Dict[str, Any]] = []
        for symbol, name in symbols:
            market_meta = self._lookup_symbol_meta(symbol)
            entries.append(
                {
                    "symbol": symbol,
                    "name": name or symbol,
                    "display": f"{name or symbol} {symbol}",
                    "table": symbol,
                    "last_price": market_meta.get("last_price"),
                    "change_percent": market_meta.get("change_percent"),
                }
            )
        manager.populate(entries, is_sample=False)

    def _prompt_watchlist_name(self, title: str, default: str = "") -> Optional[str]:
        text, ok = QtWidgets.QInputDialog.getText(self, title, "输入自选分组名称:", text=default)
        name = text.strip()
        if not ok or not name:
            return None
        return name

    def _create_watchlist(self) -> None:
        store = getattr(self._host, "watchlist_store", None)
        if store is None:
            return
        name = self._prompt_watchlist_name("新建自选分组", "自选分组")
        if not name:
            return
        try:
            wid = store.create_watchlist(name)
            self._host.current_watchlist_id = wid
            self._init_watchlists()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "创建失败", str(exc))

    def _rename_watchlist(self) -> None:
        store = getattr(self._host, "watchlist_store", None)
        tabs = getattr(self, "_watchlist_tabs", None)
        if store is None or tabs is None:
            return
        current_idx = tabs.currentIndex()
        current_id = tabs.tabData(current_idx)
        if not current_id:
            return
        current_name = tabs.tabText(current_idx)
        new_name = self._prompt_watchlist_name("重命名自选分组", current_name)
        if not new_name:
            return
        try:
            store.rename_watchlist(int(current_id), new_name)
            self._init_watchlists()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "重命名失败", str(exc))

    def _delete_watchlist(self) -> None:
        store = getattr(self._host, "watchlist_store", None)
        tabs = getattr(self, "_watchlist_tabs", None)
        if store is None or tabs is None:
            return
        current_idx = tabs.currentIndex()
        watchlist_id = tabs.tabData(current_idx)
        if not watchlist_id:
            return
        confirm = QtWidgets.QMessageBox.question(
            self, "删除确认", f"确定删除自选分组「{tabs.tabText(current_idx)}」吗？"
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        try:
            store.delete_watchlist(int(watchlist_id))
            self._host.current_watchlist_id = None
            self._init_watchlists()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "删除失败", str(exc))

    def _add_current_symbol_to_watchlist(self) -> None:
        controller = getattr(self._host, "kline_controller", None)
        if controller is None:
            return
        symbol = getattr(controller, "current_symbol", None) or getattr(controller, "current_table", None)
        name = getattr(controller, "current_symbol_name", "")
        if not symbol:
            QtWidgets.QMessageBox.information(self, "暂无标的", "请先在主图中加载一只股票后再添加到自选。")
            return
        try:
            self._host.add_symbols_to_watchlist([(symbol, name)])
            self.refresh_watchlist_view()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "添加失败", str(exc))

    def _remove_selected_from_watchlist(self) -> None:
        view = getattr(self, "_watchlist_view", None)
        store = getattr(self._host, "watchlist_store", None)
        if view is None or store is None:
            return
        selection = view.selectedIndexes()
        if not selection:
            QtWidgets.QMessageBox.information(self, "未选择", "请先在列表中选择要移除的股票。")
            return
        symbols = []
        for idx in selection:
            entry = idx.data(QtCore.Qt.UserRole + 1)
            if isinstance(entry, dict):
                sym = entry.get("symbol")
                if sym:
                    symbols.append(sym)
        watchlist_id = self._host.current_watchlist_id
        if not symbols or not watchlist_id:
            QtWidgets.QMessageBox.information(self, "缺少分组", "请先选择或创建自选分组。")
            return
        try:
            for sym in symbols:
                store.remove_symbol(int(watchlist_id), sym)
            self.refresh_watchlist_view()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "移除失败", str(exc))

    def _show_watchlist_menu(self, pos: QtCore.QPoint) -> None:
        view = getattr(self, "_watchlist_view", None)
        store = getattr(self._host, "watchlist_store", None)
        tabs = getattr(self, "_watchlist_tabs", None)
        if view is None or store is None or tabs is None:
            return
        index = view.indexAt(pos)
        if index.isValid():
            # Ensure the item under cursor is selected
            selection_model = view.selectionModel()
            if selection_model:
                selection_model.select(index, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        entries = self._selected_watchlist_items()
        if not entries:
            return

        current_id = self._host.current_watchlist_id
        menu = self._styled_menu(view)
        remove_action = menu.addAction("移除选中")
        remove_action.triggered.connect(self._remove_selected_from_watchlist)
        menu.addSeparator()

        # Build "move to" submenu
        try:
            groups = store.list_watchlists()
        except Exception:
            groups = []
        target_groups = [(wid, name) for wid, name in groups if current_id is None or int(wid) != int(current_id)]
        if target_groups:
            move_menu = menu.addMenu("移动到分组")
            for wid, name in target_groups:
                action = move_menu.addAction(str(name))
                action.triggered.connect(lambda _checked=False, gid=int(wid): self._move_selected_to_watchlist(gid))
        manage_action = menu.addAction("管理/新建分组...")
        manage_action.triggered.connect(self._open_watchlist_manager)
        menu.exec_(view.viewport().mapToGlobal(pos))

    def _move_selected_to_watchlist(self, target_id: int) -> None:
        store = getattr(self._host, "watchlist_store", None)
        current_id = self._host.current_watchlist_id
        if store is None or current_id is None or target_id == current_id:
            return
        entries = self._selected_watchlist_items()
        if not entries:
            QtWidgets.QMessageBox.information(self, "未选择", "请先选择要移动的股票。")
            return
        items: List[Tuple[str, str]] = []
        for entry in entries:
            sym = entry.get("symbol")
            name = entry.get("name") or entry.get("display") or sym
            if sym:
                items.append((sym, str(name)))
        if not items:
            return
        try:
            store.add_symbols(int(target_id), items)
            for sym, _ in items:
                store.remove_symbol(int(current_id), sym)
            # Switch to target group after moving
            tabs = getattr(self, "_watchlist_tabs", None)
            if tabs:
                idx = next((i for i in range(tabs.count()) if tabs.tabData(i) == int(target_id)), -1)
                if idx >= 0:
                    tabs.blockSignals(True)
                    tabs.setCurrentIndex(idx)
                    tabs.blockSignals(False)
            self._host.current_watchlist_id = int(target_id)
            self.refresh_watchlist_view(int(target_id))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "移动失败", str(exc))

    def _open_watchlist_manager(self) -> None:
        store = getattr(self._host, "watchlist_store", None)
        if store is None:
            return
        dialog = WatchlistManageDialog(store=store, current_id=self._host.current_watchlist_id, parent=self)
        dialog.exec_()
        self._init_watchlists()


class WatchlistManageDialog(QtWidgets.QDialog):
    """弹出式自选分组管理，仿雪球风格."""

    def __init__(self, *, store: Any, current_id: Optional[int] = None, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("自选分组管理")
        self.resize(420, 380)
        self.store = store
        self.current_id = current_id
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["我的分组", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        add_btn = QtWidgets.QPushButton("+ 新建分组", self)
        add_btn.clicked.connect(self._create_group)
        layout.addWidget(add_btn, alignment=QtCore.Qt.AlignCenter)

        self._refresh()

    def _refresh(self) -> None:
        try:
            groups = self.store.list_watchlists()
        except Exception:
            groups = []
        self.table.setRowCount(len(groups))
        for row, (wid, name) in enumerate(groups):
            item = QtWidgets.QTableWidgetItem(str(name))
            self.table.setItem(row, 0, item)
            rename_btn = QtWidgets.QToolButton(self.table)
            rename_btn.setText("✎")
            rename_btn.clicked.connect(lambda _checked=False, gid=wid, gname=name: self._rename_group(gid, gname))
            del_btn = QtWidgets.QToolButton(self.table)
            del_btn.setText("🗑")
            del_btn.clicked.connect(lambda _checked=False, gid=wid, gname=name: self._delete_group(gid, gname))
            btn_widget = QtWidgets.QWidget(self.table)
            btn_layout = QtWidgets.QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(4)
            btn_layout.addWidget(rename_btn)
            btn_layout.addWidget(del_btn)
            btn_layout.addStretch(1)
            self.table.setCellWidget(row, 1, btn_widget)
            if wid == self.current_id:
                self.table.selectRow(row)
        if groups and self.current_id is None:
            self.table.selectRow(0)

    def _create_group(self) -> None:
        text, ok = QtWidgets.QInputDialog.getText(self, "新建分组", "输入分组名称:")
        name = text.strip()
        if not ok or not name:
            return
        try:
            self.store.create_watchlist(name)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "创建失败", str(exc))
        self._refresh()

    def _rename_group(self, gid: int, old_name: str) -> None:
        text, ok = QtWidgets.QInputDialog.getText(self, "重命名分组", "新的名称:", text=old_name)
        name = text.strip()
        if not ok or not name:
            return
        try:
            self.store.rename_watchlist(gid, name)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "重命名失败", str(exc))
        self.current_id = gid
        self._refresh()

    def _delete_group(self, gid: int, name: str) -> None:
        confirm = QtWidgets.QMessageBox.question(self, "删除确认", f"确定删除分组「{name}」吗？")
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.store.delete_watchlist(gid)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "删除失败", str(exc))
        if self.current_id == gid:
            self.current_id = None
        self._refresh()
