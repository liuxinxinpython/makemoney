from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from PyQt5 import QtCore, QtGui, QtWidgets


class SymbolListManager(QtCore.QObject):
    """集中管理股票列表渲染、点击以及示例数据填充。"""

    def __init__(
        self,
        *,
        list_view: QtWidgets.QListView,
        select_symbol: Optional[Callable[[str], None]] = None,
        current_table_getter: Optional[Callable[[], Optional[str]]] = None,
        log_handler: Optional[Callable[[str], None]] = None,
        sample_entries: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(list_view)
        self._view = list_view
        self._select_symbol = select_symbol
        self._current_table_getter = current_table_getter
        self._log = log_handler or (lambda _msg: None)
        self._sample_entries: List[Dict[str, Any]] = [dict(entry) for entry in (sample_entries or [])]
        self._sample_rendered = False
        self._model = _SymbolListModel()
        self._delegate = _SymbolListDelegate(self._view)
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self._view.setSpacing(2)
        self._view.setUniformItemSizes(True)
        self._view.clicked.connect(self._handle_index_clicked)

    # ------------------------------------------------------------------
    def populate(self, entries: Iterable[Dict[str, Any]], *, is_sample: bool = False) -> None:
        dataset = entries if isinstance(entries, list) else list(entries)
        self._model.set_entries(dataset)
        self._view.setVisible(True)
        if is_sample:
            self._sample_rendered = True

    def ensure_sample_symbols(self) -> None:
        if not self._sample_rendered and self._sample_entries:
            self.populate(self._sample_entries, is_sample=True)

    def highlight_current(self) -> None:
        identifier = self._current_table_getter() if self._current_table_getter else None
        self.highlight_identifier(identifier)

    def highlight_identifier(self, identifier: Optional[str]) -> None:
        if identifier:
            self._select_item(identifier)

    def update_sample_entries(self, entries: Sequence[Dict[str, Any]]) -> None:
        self._sample_entries = [dict(entry) for entry in entries]
        self._sample_rendered = False

    # ------------------------------------------------------------------
    def _handle_index_clicked(self, index: QtCore.QModelIndex) -> None:
        if self._select_symbol is None:
            return
        entry = index.data(_SymbolListModel.EntryRole) or {}
        table = entry.get("table") or entry.get("symbol")
        if table:
            self._select_symbol(table)

    def _select_item(self, identifier: str) -> None:
        row = self._model.row_for_identifier(identifier)
        if row < 0:
            return
        index = self._model.index(row, 0)
        selection_model = self._view.selectionModel()
        if selection_model:
            selection_model.blockSignals(True)
            selection_model.select(index, QtCore.QItemSelectionModel.ClearAndSelect)
            selection_model.blockSignals(False)
        self._view.scrollTo(index, QtWidgets.QAbstractItemView.PositionAtCenter)


class _SymbolListModel(QtCore.QAbstractListModel):
    EntryRole = QtCore.Qt.UserRole + 1

    def __init__(self) -> None:
        super().__init__()
        self._entries: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._entries)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid() or not (0 <= index.row() < len(self._entries)):
            return None
        entry = self._entries[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return entry.get("display") or entry.get("symbol") or entry.get("table") or "-"
        if role == self.EntryRole:
            return entry
        return None

    # ------------------------------------------------------------------
    def set_entries(self, entries: Sequence[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._entries = [dict(entry) for entry in entries]
        self.endResetModel()

    def row_for_identifier(self, identifier: str) -> int:
        for idx, entry in enumerate(self._entries):
            if entry.get("table") == identifier or entry.get("symbol") == identifier:
                return idx
        return -1


class _SymbolListDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._name_font = QtGui.QFont()
        self._name_font.setPointSize(self._name_font.pointSize() + 1)
        self._name_font.setWeight(QtGui.QFont.Medium)
        self._code_font = QtGui.QFont()
        self._code_font.setPointSize(self._code_font.pointSize() - 1)
        self._badge_font = QtGui.QFont(self._code_font)
        self._badge_font.setPointSize(self._badge_font.pointSize() - 1)
        self._price_font = QtGui.QFont()
        self._price_font.setPointSize(self._price_font.pointSize())
        self._price_font.setWeight(QtGui.QFont.Medium)

    # ------------------------------------------------------------------
    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:  # type: ignore[override]
        entry = index.data(_SymbolListModel.EntryRole) or {}
        painter.save()
        self._draw_background(painter, option)
        rect = option.rect.adjusted(10, 8, -10, -8)

        name = self._text(entry.get("name") or entry.get("symbol"))
        symbol = self._text(entry.get("symbol") or entry.get("table"))
        exchange = self._infer_exchange(symbol)
        price = self._format_price(entry.get("last_price"))
        change = self._format_change(entry.get("change_percent"))
        trend_color = self._trend_color(entry.get("change_percent"))

        spacing = 6
        baseline_offset = 0

        price_metrics = QtGui.QFontMetrics(self._price_font)
        change_metrics = QtGui.QFontMetrics(self._price_font)
        badge_metrics = QtGui.QFontMetrics(self._badge_font)

        price_width = max(64, price_metrics.horizontalAdvance(price) + 8)
        change_width = max(58, change_metrics.horizontalAdvance(change) + 8)
        badge_width = badge_metrics.horizontalAdvance(exchange) + 12 if exchange else 0
        badge_height = 14

        text_width = rect.width() - price_width - change_width - spacing * 3

        # 左侧名称
        painter.setPen(QtGui.QColor("#161a23"))
        painter.setFont(self._name_font)
        name_rect = QtCore.QRect(rect.left(), rect.top(), text_width, rect.height() // 2 + baseline_offset)
        painter.drawText(name_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, name)

        # 代码行与交易所徽标
        code_rect = QtCore.QRect(rect.left(), rect.top() + rect.height() // 2, text_width, rect.height() // 2 - baseline_offset)
        painter.setFont(self._code_font)
        painter.setPen(QtGui.QColor("#5f6b7c"))

        x = code_rect.left()
        if exchange:
            badge_rect = QtCore.QRect(x, code_rect.center().y() - badge_height // 2, badge_width, badge_height)
            self._draw_badge(painter, badge_rect, exchange)
            x = badge_rect.right() + 6

        code_text_rect = QtCore.QRect(x, code_rect.top(), text_width - (x - code_rect.left()), code_rect.height())
        painter.drawText(code_text_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, symbol)

        # 价格列
        price_rect = QtCore.QRect(rect.right() - change_width - spacing - price_width, rect.top(), price_width, rect.height())
        painter.setFont(self._price_font)
        painter.setPen(trend_color)
        painter.drawText(price_rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, price)

        # 涨跌幅列
        change_rect = QtCore.QRect(rect.right() - change_width, rect.top(), change_width, rect.height())
        painter.drawText(change_rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, change)

        # 底部分割线
        painter.setPen(QtGui.QColor("#e5e8f0"))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

        painter.restore()

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtCore.QSize:  # type: ignore[override]
        return QtCore.QSize(option.rect.width(), 60)

    # ------------------------------------------------------------------
    def _draw_background(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem) -> None:
        if option.state & QtWidgets.QStyle.State_Selected:
            painter.fillRect(option.rect, QtGui.QColor("#e6f0ff"))
        elif option.state & QtWidgets.QStyle.State_MouseOver:
            painter.fillRect(option.rect, QtGui.QColor("#f4f6fb"))
        else:
            painter.fillRect(option.rect, QtGui.QColor("#ffffff"))

    def _text(self, value: Optional[Any]) -> str:
        if value is None:
            return "-"
        return str(value)

    def _format_price(self, value: Optional[Any]) -> str:
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return "--"
        return f"{float_value:.2f}"

    def _format_change(self, value: Optional[Any]) -> str:
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return "--"
        sign = "+" if float_value > 0 else ""
        return f"{sign}{float_value:.2f}%"

    def _trend_color(self, value: Optional[Any]) -> QtGui.QColor:
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return QtGui.QColor("#1d2331")
        if float_value > 0:
            return QtGui.QColor("#d9304c")
        if float_value < 0:
            return QtGui.QColor("#13a467")
        return QtGui.QColor("#1d2331")

    def _draw_badge(self, painter: QtGui.QPainter, rect: QtCore.QRect, text: str) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#f5f7fb"))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setFont(self._badge_font)
        painter.setPen(QtGui.QColor("#d9304c"))
        painter.drawText(rect, QtCore.Qt.AlignCenter, text)
        painter.restore()

    def _infer_exchange(self, symbol: str) -> str:
        digits = symbol.strip().upper()
        if digits.startswith("SH"):
            return "SH"
        if digits.startswith("SZ"):
            return "SZ"
        if digits.startswith("BK"):
            return "BK"
        if digits.startswith("6"):
            return "SH"
        if digits.startswith("0") or digits.startswith("3"):
            return "SZ"
        if digits.startswith("8") or digits.startswith("4"):
            return "BJ"
        return ""

