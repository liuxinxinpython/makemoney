from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt5 import QtCore, QtWidgets

if TYPE_CHECKING:  # pragma: no cover
    from ...main_ui import MainWindow


class SnowDataPage(QtWidgets.QWidget):
    """Snow 风格的数据管理页。"""

    def __init__(self, *, host: "MainWindow", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._host = host
        self._apply_styles()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        controls = self._build_controls_panel()
        layout.addWidget(controls, 0)

        content = self._build_content_panel()
        layout.addWidget(content, 1)

    def _apply_styles(self) -> None:
        # 给数据页单独的卡片和按钮样式，避免影响其他页面。
        self.setStyleSheet(
            """
QFrame#snowDataControls {
    background: transparent;
    max-width: 300px;
}
QFrame#snowDataContent {
    background: transparent;
}
QFrame#snowDataCard,
QFrame#snowDataActionCard {
    background: #ffffff;
    border: 1px solid #e3e8f3;
    border-radius: 12px;
}
QLabel#snowDataHeader {
    font-size: 20px;
    font-weight: 700;
    color: #0f1c3f;
}
QLabel#snowDataSubHeader {
    color: #5f6783;
    font-size: 12px;
    line-height: 1.4;
}
QLabel#snowDataCardTitle {
    font-size: 13px;
    font-weight: 600;
    color: #1c2440;
}
QLabel#snowDataValue {
    font-size: 13px;
    font-weight: 600;
    color: #0f1c3f;
}
QLabel#snowDataHint {
    color: #687189;
    font-size: 12px;
    line-height: 1.4;
}
QLabel#snowDataBadge {
    background: #eef3ff;
    color: #1f5eff;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}
QToolButton[class~="snowAction"] {
    text-align: left;
    background: #f8faff;
    border: 1px solid #e3e8f3;
    border-radius: 10px;
    padding: 10px 12px;
    font-weight: 600;
    color: #1c2440;
}
QToolButton[class~="snowAction"]:hover {
    background: #ecf1ff;
    border-color: #d2dcff;
}
"""
        )

    # --- panels -----------------------------------------------------------
    def _build_controls_panel(self) -> QtWidgets.QWidget:
        host = self._host
        panel = QtWidgets.QFrame(self)
        panel.setObjectName("snowDataControls")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._create_section_label("数据操作", panel))

        actions_card = QtWidgets.QFrame(panel)
        actions_card.setObjectName("snowDataActionCard")
        actions_layout = QtWidgets.QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(14, 14, 14, 14)
        actions_layout.setSpacing(8)

        data_actions = [
            (host.action_choose_dir, "选择 Excel/CSV 目录用于批量导入"),
            (host.action_choose_db, "指定或创建 SQLite 数据库文件"),
            (host.action_import_append, "将新数据追加至现有表"),
            (host.action_import_replace, "重建表并覆盖旧数据"),
            (host.action_refresh_symbols, "刷新标的列表缓存"),
        ]
        for action, tooltip in data_actions:
            if action is None:
                continue
            button = self._create_action_button(actions_card, action=action)
            button.setProperty("class", "snowAction")
            button.setToolTip(tooltip)
            actions_layout.addWidget(button)

        layout.addWidget(actions_card)

        hint = QtWidgets.QLabel("操作前先确认目录与数据库路径，导入过程可随时打开日志查看详情。", panel)
        hint.setObjectName("snowDataHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return panel

    def _build_content_panel(self) -> QtWidgets.QWidget:
        host = self._host
        panel = QtWidgets.QFrame(self)
        panel.setObjectName("snowDataContent")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = self._create_header(panel)
        layout.addWidget(header)

        summary_row = QtWidgets.QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(12)

        dir_body = QtWidgets.QWidget(panel)
        dir_layout = QtWidgets.QVBoxLayout(dir_body)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(6)
        host.data_dir_value_label = QtWidgets.QLabel(host._format_path(host.data_dir), dir_body)
        host.data_dir_value_label.setObjectName("snowDataValue")
        host.data_dir_value_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        host.data_dir_value_label.setWordWrap(True)
        dir_layout.addWidget(host.data_dir_value_label)
        dir_hint = QtWidgets.QLabel("选择包含 Excel/CSV 的目录，导入时会递归读取。", dir_body)
        dir_hint.setObjectName("snowDataHint")
        dir_hint.setWordWrap(True)
        dir_layout.addWidget(dir_hint)
        summary_row.addWidget(self._create_data_card("数据目录", dir_body, panel), 1)

        db_body = QtWidgets.QWidget(panel)
        db_layout = QtWidgets.QVBoxLayout(db_body)
        db_layout.setContentsMargins(0, 0, 0, 0)
        db_layout.setSpacing(6)
        host.data_db_value_label = QtWidgets.QLabel(host._format_path(host.db_path), db_body)
        host.data_db_value_label.setObjectName("snowDataValue")
        host.data_db_value_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        host.data_db_value_label.setWordWrap(True)
        db_layout.addWidget(host.data_db_value_label)
        db_hint = QtWidgets.QLabel("当前 SQLite 数据库文件路径，可手动切换。", db_body)
        db_hint.setObjectName("snowDataHint")
        db_hint.setWordWrap(True)
        db_layout.addWidget(db_hint)
        summary_row.addWidget(self._create_data_card("数据库信息", db_body, panel), 1)

        layout.addLayout(summary_row)

        layout.addWidget(self._create_tushare_card(panel))

        status_body = QtWidgets.QWidget(panel)
        status_layout = QtWidgets.QVBoxLayout(status_body)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_header = QtWidgets.QHBoxLayout()
        status_header.setContentsMargins(0, 0, 0, 0)
        status_header.setSpacing(6)
        badge = self._create_badge("导入状态", status_body)
        status_header.addWidget(badge, 0)
        status_header.addStretch(1)
        status_layout.addLayout(status_header)

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

        tips_body = QtWidgets.QWidget(panel)
        tips_layout = QtWidgets.QVBoxLayout(tips_body)
        tips_layout.setContentsMargins(0, 0, 0, 0)
        tips_layout.setSpacing(6)
        tips = [
            "首选先设置数据目录与数据库，再启动导入任务；",
            "导入完成后可点击“刷新标的列表”同步到行情页；",
            "如需重建，请确保数据库文件有备份或可覆盖。",
        ]
        for tip in tips:
            label = QtWidgets.QLabel(f"· {tip}", tips_body)
            label.setObjectName("snowDataHint")
            label.setWordWrap(True)
            tips_layout.addWidget(label)
        layout.addWidget(self._create_data_card("小贴士", tips_body, panel))

        layout.addStretch(1)
        return panel

    # --- helpers ---------------------------------------------------------
    def _create_tushare_card(self, parent: QtWidgets.QWidget) -> QtWidgets.QFrame:
        host = self._host
        body = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        token_input = QtWidgets.QLineEdit(body)
        token_input.setPlaceholderText("粘贴你的 Tushare Pro Token")
        token_input.setEchoMode(QtWidgets.QLineEdit.Normal)  # 不隐藏，便于确认
        token_input.setClearButtonEnabled(True)
        host.tushare_token_input = token_input
        if host.tushare_token:
            token_input.setText(host.tushare_token)
        layout.addWidget(token_input)

        hint = QtWidgets.QLabel("基础积分：每分钟 500 次请求，每次 6000 条日线数据。默认增量补齐，如无本地数据则拉取近两年。", body)
        hint.setObjectName("snowDataHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        date_row = QtWidgets.QHBoxLayout()
        date_row.setContentsMargins(0, 0, 0, 0)
        date_row.setSpacing(8)
        start_edit = QtWidgets.QDateEdit(body)
        start_edit.setCalendarPopup(True)
        start_edit.setDisplayFormat("yyyy-MM-dd")
        end_edit = QtWidgets.QDateEdit(body)
        end_edit.setCalendarPopup(True)
        end_edit.setDisplayFormat("yyyy-MM-dd")
        today = QtCore.QDate.currentDate()
        start_edit.setDate(today.addDays(-30))
        end_edit.setDate(today)
        host.tushare_start_date = start_edit
        host.tushare_end_date = end_edit
        date_row.addWidget(QtWidgets.QLabel("开始日期", body))
        date_row.addWidget(start_edit)
        date_row.addWidget(QtWidgets.QLabel("结束日期", body))
        date_row.addWidget(end_edit)
        layout.addLayout(date_row)

        buttons_row = QtWidgets.QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)
        save_btn = QtWidgets.QPushButton("保存 Token", body)
        save_btn.clicked.connect(host.save_tushare_token)
        update_btn = QtWidgets.QPushButton("用 Tushare 更新日线", body)
        update_btn.setProperty("class", "primary")
        update_btn.clicked.connect(host.start_tushare_update)
        test_btn = QtWidgets.QPushButton("测试接口", body)
        test_btn.clicked.connect(host.start_tushare_test)
        buttons_row.addWidget(save_btn)
        buttons_row.addWidget(update_btn, 1)
        buttons_row.addWidget(test_btn)
        layout.addLayout(buttons_row)

        status_label = QtWidgets.QLabel("等待同步", body)
        status_label.setObjectName("snowDataHint")
        host.tushare_status_label = status_label
        layout.addWidget(status_label)

        return self._create_data_card("Tushare 日线更新", body, parent)

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

    def _create_header(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        header = QtWidgets.QFrame(parent)
        header_layout = QtWidgets.QVBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(4)
        title = QtWidgets.QLabel("数据管理中心", header)
        title.setObjectName("snowDataHeader")
        subtitle = QtWidgets.QLabel("选择数据目录与数据库，启动导入并跟踪进度；导入完成后刷新标的列表。", header)
        subtitle.setObjectName("snowDataSubHeader")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        return header

    def _create_badge(self, text: str, parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
        badge = QtWidgets.QLabel(text, parent)
        badge.setObjectName("snowDataBadge")
        badge.setAlignment(QtCore.Qt.AlignCenter)
        return badge
