from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from PyQt5 import QtCore, QtWidgets

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
    border-bottom-color: #1f6dff;
}
QTabBar#snowCategoryTabs::tab:hover {
    color: #1f6dff;
}
"""
        )
        tabs_layout.addWidget(category_bar)
        self._host.symbol_tabs = category_bar

        market_bar = QtWidgets.QTabBar(tabs_container)
        market_bar.setObjectName("snowMarketTabs")
        market_bar.setDrawBase(False)
        market_bar.setExpanding(False)
        market_bar.setUsesScrollButtons(False)
        market_bar.setElideMode(QtCore.Qt.ElideRight)
        market_bar.setFocusPolicy(QtCore.Qt.NoFocus)
        market_labels = ["全部", "沪深", "港股", "美股", "模拟", "盯住"]
        for idx, label in enumerate(market_labels):
            market_bar.addTab(label)
            if idx != 0:
                market_bar.setTabEnabled(idx, False)
        market_bar.setCurrentIndex(0)
        market_bar.setStyleSheet(
            """
QTabBar#snowMarketTabs {
    background: transparent;
    padding-left: 6px;
}
QTabBar#snowMarketTabs::tab {
    color: #919bb4;
    padding: 3px 12px;
    margin-right: 6px;
    border-radius: 12px;
    font-size: 12px;
    min-width: 0;
    background: transparent;
}
QTabBar#snowMarketTabs::tab:selected {
    color: #1f6dff;
    font-weight: 600;
}
QTabBar#snowMarketTabs::tab:hover {
    color: #1f6dff;
}
QTabBar#snowMarketTabs::tab:disabled {
    color: #c0c6d8;
}
"""
        )
        tabs_layout.addWidget(market_bar)

        stack = QtWidgets.QStackedWidget(tabs_container)
        tabs_layout.addWidget(stack, 1)

        all_tab = QtWidgets.QWidget(stack)
        all_layout = QtWidgets.QVBoxLayout(all_tab)
        all_layout.setContentsMargins(0, 0, 0, 0)
        all_layout.setSpacing(6)
        all_layout.addWidget(self._create_symbol_list_header(all_tab))
        all_list = QtWidgets.QListView(all_tab)
        all_list.setObjectName("snowAllSymbols")
        all_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        all_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        all_list.setSpacing(2)
        all_layout.addWidget(all_list, 1)
        stack.addWidget(all_tab)
        self._host.all_symbol_list = all_list

        fav_tab = QtWidgets.QWidget(stack)
        fav_layout = QtWidgets.QVBoxLayout(fav_tab)
        fav_layout.setContentsMargins(0, 0, 0, 0)
        fav_layout.setSpacing(6)
        fav_layout.addWidget(self._create_symbol_list_header(fav_tab))
        fav_list = QtWidgets.QListWidget(fav_tab)
        fav_list.setObjectName("snowFavoriteSymbols")
        fav_list.setEnabled(False)
        fav_list.addItem("自选列表建设中")
        fav_layout.addWidget(fav_list, 1)
        stack.addWidget(fav_tab)
        self._host.favorite_symbol_list = fav_list

        category_bar.currentChanged.connect(stack.setCurrentIndex)
        category_bar.currentChanged.connect(lambda idx: fav_list.setDisabled(idx != 1))
        stack.setCurrentIndex(category_bar.currentIndex())

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

