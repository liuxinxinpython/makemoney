from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt5 import QtCore, QtWidgets

if TYPE_CHECKING:  # pragma: no cover
    from ...main_ui import MainWindow


class SnowDataPage(QtWidgets.QWidget):
    """Snow盈风格数据管理页。"""

    def __init__(self, *, host: "MainWindow", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._host = host
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)

        controls = self._build_controls_panel()
        layout.addWidget(controls)

        content = self._build_content_panel()
        layout.addWidget(content, 1)

    # --- panels -----------------------------------------------------------
    def _build_controls_panel(self) -> QtWidgets.QWidget:
        host = self._host
        panel = QtWidgets.QFrame(self)
        panel.setObjectName("snowDataControls")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._create_section_label("数据操作", panel))

        data_actions = [
            host.action_choose_dir,
            host.action_choose_db,
            host.action_import_append,
            host.action_import_replace,
            host.action_refresh_symbols,
        ]
        for action in data_actions:
            if action is None:
                continue
            layout.addWidget(self._create_action_button(panel, action=action))
        layout.addStretch(1)
        return panel

    def _build_content_panel(self) -> QtWidgets.QWidget:
        host = self._host
        panel = QtWidgets.QFrame(self)
        panel.setObjectName("snowDataContent")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = QtWidgets.QLabel("数据管理中心", panel)
        header.setObjectName("snowDataHeader")
        layout.addWidget(header)

        dir_body = QtWidgets.QWidget(panel)
        dir_layout = QtWidgets.QVBoxLayout(dir_body)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(6)
        host.data_dir_value_label = QtWidgets.QLabel(host._format_path(host.data_dir), dir_body)
        host.data_dir_value_label.setObjectName("snowDataValue")
        dir_layout.addWidget(host.data_dir_value_label)
        dir_hint = QtWidgets.QLabel("请选择包含 Excel/CSV 的目录以便导入。", dir_body)
        dir_hint.setObjectName("snowDataHint")
        dir_layout.addWidget(dir_hint)
        layout.addWidget(self._create_data_card("数据目录状态", dir_body, panel))

        db_body = QtWidgets.QWidget(panel)
        db_layout = QtWidgets.QVBoxLayout(db_body)
        db_layout.setContentsMargins(0, 0, 0, 0)
        db_layout.setSpacing(6)
        host.data_db_value_label = QtWidgets.QLabel(host._format_path(host.db_path), db_body)
        host.data_db_value_label.setObjectName("snowDataValue")
        db_layout.addWidget(host.data_db_value_label)
        db_hint = QtWidgets.QLabel("当前 SQLite 数据库位置。", db_body)
        db_hint.setObjectName("snowDataHint")
        db_layout.addWidget(db_hint)
        layout.addWidget(self._create_data_card("数据库信息", db_body, panel))

        status_body = QtWidgets.QWidget(panel)
        status_layout = QtWidgets.QVBoxLayout(status_body)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        host.import_status_label = QtWidgets.QLabel("待命", status_body)
        host.import_status_label.setObjectName("snowDataValue")
        status_layout.addWidget(host.import_status_label)
        host.data_page_progress = QtWidgets.QProgressBar(status_body)
        host.data_page_progress.setVisible(False)
        host.data_page_progress.setRange(0, 1)
        status_layout.addWidget(host.data_page_progress)
        log_button = QtWidgets.QPushButton("查看导入日志", status_body)
        log_button.clicked.connect(lambda: host.show_log_console(show=True))
        status_layout.addWidget(log_button)
        layout.addWidget(self._create_data_card("导入任务", status_body, panel))

        layout.addStretch(1)
        return panel

    # --- helpers ---------------------------------------------------------
    def _create_section_label(self, text: str, parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, parent)
        label.setObjectName("snowNavSectionLabel")
        label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        return label

    def _create_action_button(
        self,
        parent: QtWidgets.QWidget,
        *,
        action: QtWidgets.QAction,
    ) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton(parent)
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        button.setCursor(QtCore.Qt.PointingHandCursor)
        button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        button.setDefaultAction(action)
        return button

    def _create_data_card(
        self,
        title: str,
        body: QtWidgets.QWidget,
        parent: QtWidgets.QWidget,
    ) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame(parent)
        card.setObjectName("snowDataCard")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        title_label = QtWidgets.QLabel(title, card)
        title_label.setObjectName("snowDataCardTitle")
        layout.addWidget(title_label)
        layout.addWidget(body)
        return card
