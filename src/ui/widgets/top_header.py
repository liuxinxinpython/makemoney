from __future__ import annotations

from typing import Callable, Optional

from PyQt5 import QtCore, QtGui, QtWidgets


class SnowTopHeader(QtWidgets.QFrame):
    def __init__(
        self,
        *,
        parent: Optional[QtWidgets.QWidget] = None,
        search_widget: Optional[QtWidgets.QWidget] = None,
        on_strategy_clicked: Optional[Callable[[], None]] = None,
        on_minimize: Optional[Callable[[], None]] = None,
        on_maximize_toggle: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        logo_text: str = "雪",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("snowTopHeader")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(12)

        logo = QtWidgets.QFrame(self)
        logo.setObjectName("snowHeaderLogo")
        logo.setFixedSize(36, 36)
        logo_layout = QtWidgets.QHBoxLayout(logo)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(0)
        logo_label = QtWidgets.QLabel(logo_text, logo)
        logo_label.setObjectName("snowHeaderLogoText")
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_layout.addWidget(logo_label)
        layout.addWidget(logo, 0, QtCore.Qt.AlignVCenter)

        search_frame = QtWidgets.QFrame(self)
        search_frame.setObjectName("snowSearchFrame")
        search_layout = QtWidgets.QHBoxLayout(search_frame)
        search_layout.setContentsMargins(12, 4, 12, 4)
        search_layout.setSpacing(8)
        search_label = QtWidgets.QLabel("代码/名称/拼音", search_frame)
        search_label.setObjectName("snowSearchLabel")
        search_layout.addWidget(search_label)
        if search_widget is not None:
            search_widget.setParent(search_frame)
            search_layout.addWidget(search_widget, 1)
        else:
            filler = QtWidgets.QLineEdit(search_frame)
            filler.setPlaceholderText("代码/名称/拼音")
            search_layout.addWidget(filler, 1)
        layout.addWidget(search_frame, 2)

        self.drag_area = QtWidgets.QWidget(self)
        self.drag_area.setObjectName("snowHeaderDragArea")
        self.drag_area.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.drag_area.setCursor(QtCore.Qt.ArrowCursor)
        layout.addWidget(self.drag_area, 1)

        right_container = QtWidgets.QFrame(self)
        right_container.setObjectName("snowHeaderActions")
        right_layout = QtWidgets.QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        for text in ("反馈", "客服", "设置"):
            btn = QtWidgets.QToolButton(right_container)
            btn.setAutoRaise(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setText(text)
            right_layout.addWidget(btn)

        self.strategy_button: Optional[QtWidgets.QToolButton] = None

        controls_container = QtWidgets.QFrame(right_container)
        controls_layout = QtWidgets.QHBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)

        self.min_button = self._create_window_button(
            parent=controls_container,
            icon_role=QtWidgets.QStyle.SP_TitleBarMinButton,
            handler=on_minimize,
        )
        controls_layout.addWidget(self.min_button)
        self.max_button = self._create_window_button(
            parent=controls_container,
            icon_role=QtWidgets.QStyle.SP_TitleBarMaxButton,
            handler=on_maximize_toggle,
        )
        controls_layout.addWidget(self.max_button)
        self.close_button = self._create_window_button(
            parent=controls_container,
            icon_role=QtWidgets.QStyle.SP_TitleBarCloseButton,
            handler=on_close,
        )
        controls_layout.addWidget(self.close_button)

        right_layout.addWidget(controls_container)
        layout.addWidget(right_container, 0)

    def _create_window_button(
        self,
        *,
        parent: QtWidgets.QWidget,
        icon_role: QtWidgets.QStyle.StandardPixmap,
        handler: Optional[Callable[[], None]],
    ) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton(parent)
        button.setAutoRaise(True)
        button.setCursor(QtCore.Qt.PointingHandCursor)
        button.setFixedSize(32, 24)
        try:
            button.setIcon(QtWidgets.QApplication.style().standardIcon(icon_role))
        except Exception:
            pass
        if handler:
            button.clicked.connect(handler)
        return button