# A股K线分析工具

一个基于 PyQt5 与 TradingView 模板的桌面端分析工具，用于浏览本地 SQLite 中的 A 股日线数据，并围绕 ZigZag 波峰波谷策略提供策略研究工作台、批量扫描与轻量回测能力。

## 功能亮点

- **TradingView 嵌入式图表**：通过自定义 HTML 模板在 QWebEngine 中渲染交互式 K 线。
- **ECharts Demo**：内置“视图 → ECharts 演示”入口，可对比另一套开源图表的可扩展性。
- **异步数据导入**：Excel/CSV → SQLite 全流程在后台线程完成，支持追加或重建模式并实时输出日志。
- **大库加载优化**：股票列表和 K 线数据使用后台 worker + 缓存策略，4GB 级数据库仍可流畅浏览。
- **策略工作台**：右侧 Dock 面板集中 ZigZag 参数配置、即时预览、批量扫描和历史回测，结果可直接回填主图。
- **统一 ZigZag 实现**：所有策略分析均由 `zigzag_wave_peaks_valleys` 提供，便于调参和维护。
- **缠论买卖点策略**：内置分型/笔/中枢识别，自动标注一买/二买/一卖/二卖并高亮中枢区间。

## 运行环境

- Windows 10+（推荐，开发环境）或支持 PyQt5 的其他桌面系统
- Python 3.9 及以上
- 依赖：`PyQt5`, `PyQtWebEngine`, `pandas`, `numpy`, `scipy`, `akshare`（可选，用于补数）

## 快速开始

```bash
git clone https://github.com/liuxinxinpython/makemoney.git
cd makemoney
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS 请改为 source .venv/bin/activate
pip install PyQt5 PyQtWebEngine pandas numpy scipy akshare
python main.py
```

如需使用 Excel/CSV 导入功能，请确保 `src/data/import_excel_to_sqlite.py` 中的依赖均可导入（如 `openpyxl`、`pandas`）。

## 使用流程

1. **启动程序**：运行 `python main.py`，主界面会在中央显示 TradingView 图表。
2. **绑定数据库**：在菜单 `数据 > 选择数据库文件...` 指定或创建 SQLite，工具栏会实时展示当前路径。
3. **准备导入目录**：点击工具栏“选择数据目录”，再通过“导入”下拉按钮选择“追加”或“重建”模式。
4. **刷新标的并筛选**：股票下拉框支持后台刷新与关键字搜索，便于在大盘子里快速定位。
5. **查看策略结果**：工具栏 `策略选股` 按钮会打开右侧策略工作台，可配置最小反转幅度、触发即时预览或批量扫描，扫描结果双击即可将标的带回主图。
6. **监控日志**：数据导入和策略执行均会写入独立日志对话框，同时在状态栏显示进度条。

## 目录结构（节选）

```
makemoney/
├── main.py                # 程序入口，负责 QApplication 启动
├── README.md
└── src/
    ├── main_ui.py         # 主窗口与工具栏、Dock 组织
    ├── data/              # 数据导入、加载与后台 worker
    ├── displays/          # 图表显示适配器，当前注册 TradingView ChartDisplay
    ├── rendering/         # TradingView HTML 模板与渲染工具
    ├── research/          # 策略注册中心、批量扫描与回测模型
    ├── strategies/        # `zigzag_wave_peaks_valleys.py` 保留的唯一策略实现
    └── ui/                # K 线控制器与策略工作台控制器
```

## 开发说明

- **控制器解耦**：`KLineController` 负责数据与图表联动；`StrategyWorkbenchController` 控制 Dock 面板、信号与回测流程；主窗口仅处理装配。
- **策略唯一来源**：历史的 `advanced_*/double_bottom/pattern_scanner` 已清理，`strategies/__init__.py` 现在只导出 `ZigZagWavePeaksValleysStrategy`。
- **扩展策略**：若需加入新策略，请在 `strategies/` 中实现，并在工作台控制器中注册对应的预览/扫描/回测入口。
- **模板自定义**：修改 `src/rendering/templates/tradingview_template.html` 即可调整图形主题、指标或交互事件。

## 数据导入要点

- 支持 `.xls/.xlsx/.xlsm/.xlsb/.csv`，可根据数据量选择“追加”或“重建”模式。
- 导入任务在后台线程执行，并通过日志窗口输出进度；状态栏的进度条可以判断任务是否仍在运行。
- 若数据库很大，建议先刷新标的列表（工具栏按钮）再开始策略分析，避免旧缓存影响结果。

## 贡献与许可

- 欢迎通过 Issue/Pull Request 报告问题或贡献新特性。
- 开发建议：为每个功能创建独立分支，提交信息使用 `feat/fix/chore` 前缀描述变更。
- 项目采用 MIT License，详细条款见 `LICENSE`。