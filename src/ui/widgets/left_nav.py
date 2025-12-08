from __future__ import annotations

from typing import Callable, Dict, Optional

from PyQt5 import QtCore, QtGui, QtWidgets


class SnowLeftNav(QtWidgets.QFrame):
    def __init__(
        self,
        *,
        parent: Optional[QtWidgets.QWidget] = None,
        nav_items: Dict[str, Callable[[], None]] | None = None,
        footer_items: Dict[str, Callable[[], None]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("snowLeftNav")
        self.setFixedWidth(92)
        self.setStyleSheet(
            """
#snowLeftNav {
    background-color: #f2f4f8;
    border: none;
    border-radius: 0;
    border-right: 1px solid #e0e3eb;
}
"""
        )
        self.buttons: Dict[str, QtWidgets.QToolButton] = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 18, 0, 18)
        layout.setSpacing(12)

        if nav_items:
            for key, handler in nav_items.items():
                layout.addWidget(self._create_nav_button(key, handler), alignment=QtCore.Qt.AlignHCenter)

        layout.addStretch(1)

        if footer_items:
            for key, handler in footer_items.items():
                layout.addWidget(
                    self._create_nav_button(key, handler, checkable=False),
                    alignment=QtCore.Qt.AlignHCenter,
                )

    def _create_nav_button(
        self,
        key: str,
        handler: Callable[[], None],
        *,
        checkable: bool = True,
    ) -> QtWidgets.QToolButton:
        icon = self._resolve_icon(key)
        button = _NavButton(text=key, icon=icon, parent=self, checkable=checkable)
        button.clicked.connect(handler)
        if checkable:
            self.buttons[key] = button
        return button

    def set_active(self, key: str) -> None:
        for nav_key, button in self.buttons.items():
            is_active = nav_key == key
            button.setChecked(is_active)
            button.update()

    def _resolve_icon(self, key: str) -> QtGui.QIcon:
        style = QtWidgets.QApplication.style()
        mapping = {
            "行情": QtWidgets.QStyle.SP_DesktopIcon,
            "数据": QtWidgets.QStyle.SP_FileDialogContentsView,
            "策略": QtWidgets.QStyle.SP_ComputerIcon,
        }
        role = mapping.get(key)
        return style.standardIcon(role) if role is not None else style.standardIcon(QtWidgets.QStyle.SP_FileIcon)


class _NavButton(QtWidgets.QAbstractButton):
    def __init__(
        self,
        *,
        text: str,
        icon: QtGui.QIcon,
        parent: Optional[QtWidgets.QWidget] = None,
        checkable: bool = True,
    ) -> None:
        super().__init__(parent)
        self._icon = icon
        self._hovered = False
        self.setText(text)
        self.setCheckable(checkable)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(76, 88)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

    def sizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        return QtCore.QSize(76, 88)

    def enterEvent(self, event: QtCore.QEvent) -> None:  # type: ignore[override]
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # type: ignore[override]
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QtCore.Qt.transparent)

        is_active = self.isChecked()
        icon_bg = QtGui.QColor("#e7eaf1")
        icon_fg = QtGui.QColor("#7a849f")
        text_color = QtGui.QColor("#7a849f")

        if is_active:
            icon_bg = QtGui.QColor("#1f6dff")
            icon_fg = QtGui.QColor("#ffffff")
            text_color = QtGui.QColor("#1f6dff")
        elif self._hovered:
            icon_bg = QtGui.QColor("#dbe5ff")
            icon_fg = QtGui.QColor("#1f6dff")
            text_color = QtGui.QColor("#1f6dff")

        icon_rect = QtCore.QRect(0, 4, 40, 40)
        icon_rect.moveCenter(QtCore.QPoint(self.width() // 2, 30))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(icon_bg)
        painter.drawRoundedRect(icon_rect, 12, 12)

        if not self._icon.isNull():
            pixmap = self._render_icon(icon_fg)
            if not pixmap.isNull():
                target = icon_rect.adjusted(8, 8, -8, -8)
                painter.drawPixmap(target, pixmap)

        text_rect = QtCore.QRect(0, icon_rect.bottom() + 6, self.width(), self.height() - icon_rect.bottom() - 10)
        painter.setPen(text_color)
        text_font = painter.font()
        text_font.setPointSize(10)
        painter.setFont(text_font)
        painter.drawText(text_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, self.text())

    def _render_icon(self, color: QtGui.QColor) -> QtGui.QPixmap:
        size = 20
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        icon_painter = QtGui.QPainter(pixmap)
        icon_painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        self._icon.paint(icon_painter, QtCore.QRect(0, 0, size, size), QtCore.Qt.AlignCenter, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        icon_painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        icon_painter.fillRect(pixmap.rect(), color)
        icon_painter.end()
        return pixmap