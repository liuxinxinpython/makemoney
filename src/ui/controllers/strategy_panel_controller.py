from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt5 import QtCore, QtWidgets

if TYPE_CHECKING:  # pragma: no cover
    from ...main_ui import MainWindow


class StrategyPanelController(QtCore.QObject):
    """Orchestrates the strategy sidebar lifecycle and sizing."""

    def __init__(self, *, host: "MainWindow") -> None:
        super().__init__(host)
        self._host = host
        self._initialized = False
        self._panel_widget: Optional[QtWidgets.QWidget] = None

    # ------------------------------------------------------------------
    def focus_sidebar(self) -> None:
        host = self._host
        if host.pages and host.quotes_page:
            host.pages.setCurrentWidget(host.quotes_page)
        self.ensure_panel()
        sidebar = host.strategy_sidebar
        splitter = getattr(host, "body_splitter", None)
        if sidebar and splitter:
            if not sidebar.isVisible():
                sidebar.setVisible(True)
            index = splitter.indexOf(sidebar)
            if index >= 0:
                preferred_width = self._preferred_width()
                sizes = splitter.sizes()
                needs_resize = not sizes or index >= len(sizes) or sizes[index] < preferred_width * 0.8
                if needs_resize:
                    self._apply_width(preferred_width)
            sidebar.setFocus()
        if host.left_nav:
            host.left_nav.set_active("策略")

    def ensure_panel(self) -> None:
        if self._initialized:
            return
        host = self._host
        if host.workbench_controller is None:
            host._init_workbench_controller()
        controller = host.workbench_controller
        if controller is None:
            self._set_placeholder("策略模块不可用")
            return
        if host.strategy_panel_container is None or host.strategy_panel_layout is None:
            return
        panel = controller.create_embedded_panel(host.strategy_panel_container)
        if panel is None:
            self._set_placeholder("策略面板初始化失败")
            return
        self._clear_layout(host.strategy_panel_layout)
        host.strategy_panel_layout.addWidget(panel)
        host.strategy_panel_widget = panel
        self._panel_widget = panel
        if host.strategy_placeholder_label:
            host.strategy_placeholder_label.setVisible(False)
        self._initialized = True

    # ------------------------------------------------------------------
    def _set_placeholder(self, text: str) -> None:
        placeholder = self._host.strategy_placeholder_label
        if placeholder:
            placeholder.setText(text)
            placeholder.setVisible(True)

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _preferred_width(self) -> int:
        panel = self._panel_widget or getattr(self._host, "strategy_panel_widget", None)
        if panel is not None:
            hint = panel.sizeHint()
            if hint.isValid():
                return max(1000, hint.width() + 32)
        return 1000

    def _apply_width(self, preferred_width: int) -> None:
        host = self._host
        splitter = getattr(host, "body_splitter", None)
        sidebar = host.strategy_sidebar
        if not (splitter and sidebar):
            return
        preferred_width = max(600, preferred_width)
        sidebar.setMinimumWidth(preferred_width)
        sizes = splitter.sizes()
        total_width = sum(sizes)
        if total_width <= 0:
            total_width = max(splitter.width(), preferred_width + 700)
        left_width = 260
        center_min = 360
        reference_total = max(total_width, left_width + center_min + preferred_width)
        center_width = max(center_min, reference_total - left_width - preferred_width)
        strategy_width = reference_total - left_width - center_width
        if strategy_width < preferred_width:
            strategy_width = preferred_width
        splitter.setSizes([left_width, center_width, strategy_width])