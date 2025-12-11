# A股K线分析工具

一个基于 PyQt5 与 TradingView 模板的桌面端分析工具，用于浏览本地 SQLite 中的 A 股日线数据。最新版本将主界面改造成“导航栏 + 股票列表 + 行情图表”三段式布局，并围绕 ZigZag 波峰波谷策略提供策略研究工作台、批量扫描与轻量回测能力。

## 功能亮点

- **轻量 Snow 风格 UI**：新增侧边导航、扁平化卡片和分隔线设计，股票列表支持交易所徽章、最新价与涨跌幅的高密度展示。
- **TradingView 嵌入式图表**：自定义 HTML 模板在 QWebEngine 中渲染交互式 K 线，主图/成交量/MACD 分区均采用矩形模块与灰色分割条。
- **异步数据导入与筛选**：Excel/CSV → SQLite 由后台线程负责，股票列表搜索过滤也在独立 worker 中完成，大库（>4GB）依旧流畅。
- **缓存与热加载**：标的列表、行情数据均有缓存策略，缺少最新价/涨跌幅字段时会自动刷新数据库。
- **策略工作台**：右侧面板集中 ZigZag 参数、即时预览、批量扫描和历史回测，可随时展开或折叠。
- **统一 ZigZag 实现**：所有策略分析均使用 `zigzag_wave_peaks_valleys`，确保指标一致、调参简单。
- **Tushare 日线同步**：数据页新增 Token 输入与日期选择，可按交易日批量补齐日线数据，自动创建缺失表并刷新标的。

## 运行环境

- Windows 10+（推荐，开发环境）或支持 PyQt5 的其他桌面系统
- Python 3.9 及以上
- 依赖：`PyQt5`, `PyQtWebEngine`, `pandas`, `numpy`, `scipy`, `akshare`（可选，用于补数），`tushare`（可选，用于在线同步）

## 快速开始

```bash
git clone https://github.com/liuxinxinpython/makemoney.git
cd makemoney
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS 请改为 source .venv/bin/activate
pip install PyQt5 PyQtWebEngine pandas numpy scipy akshare tushare
# 如需提前保存 Token，可写入用户目录：Windows: echo YOUR_TOKEN > %USERPROFILE%\\.tushare_token
# macOS/Linux:  echo "YOUR_TOKEN" > ~/.tushare_token
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
7. **切换视图**：左侧导航可在“行情 / 数据 / 策略”间切换，进入行情或数据时会自动收起策略侧边栏，保持主图区域最大化。

## Tushare 日线同步

- **输入 Token**：在“数据”页的 Tushare 区域粘贴 Token，可点击“保存 Token”写入 `~/.tushare_token`（下次启动自动填充）。
- **选择日期区间**：默认补齐最近 180 天，可在起止日期选择器中指定同步范围（按交易日批量拉取并拆分写表）。
- **执行同步**：点击“用 Tushare 更新日线”，进度条与日志会实时显示请求/写入状态；任务完成后会自动刷新标的列表。
- **接口校验**：支持“测试接口”按钮快速验证 Token 可用性与 `daily` 权限，避免长任务才发现配额问题。
- **行为说明**：同步时会检测表缺失并自动创建，写入前清理重叠日期避免重复行，默认不依赖 `trade_cal` 权限。

## 目录结构（节选）

```
makemoney/
├── main.py                # 程序入口，负责 QApplication 启动
├── README.md
└── src/
    ├── main_ui.py         # 主窗口与工具栏、导航、布局组织
    ├── data/              # 数据导入、加载与后台 worker
    ├── displays/          # 图表显示适配器，当前注册 TradingView ChartDisplay
    ├── rendering/         # TradingView HTML 模板与渲染工具（行情主图扁平化样式）
    ├── research/          # 策略注册中心、批量扫描与回测模型
    ├── strategies/        # `zigzag_wave_peaks_valleys.py` 保留的唯一策略实现
    └── ui/                # 控制器、页面与自定义控件（导航、列表、主题等）
```

## 开发说明

- **控制器解耦**：`KLineController` 负责数据与图表联动；`StrategyWorkbenchController` 控制 Dock 面板、信号与回测流程；主窗口仅处理装配。
- **策略唯一来源**：历史的 `advanced_*/double_bottom/pattern_scanner` 已清理，`strategies/__init__.py` 现在只导出 `ZigZagWavePeaksValleysStrategy`。
- **扩展策略**：若需加入新策略，请在 `strategies/` 中实现，并在工作台控制器中注册对应的预览/扫描/回测入口。
- **模板自定义**：`src/rendering/templates/tradingview_template.html` 控制行情区域样式，可自定义主图/分割条/指标布局。

## 数据导入要点

- 支持 `.xls/.xlsx/.xlsm/.xlsb/.csv`，可根据数据量选择“追加”或“重建”模式。
- 导入任务在后台线程执行，并通过日志窗口输出进度；状态栏的进度条可以判断任务是否仍在运行。
- 若数据库很大，建议先刷新标的列表（工具栏按钮）再开始策略分析，避免旧缓存影响结果。

## 贡献与许可

- 欢迎通过 Issue/Pull Request 报告问题或贡献新特性。
- 开发建议：为每个功能创建独立分支，提交信息使用 `feat/fix/chore` 前缀描述变更。
- 项目采用 MIT License，详细条款见 `LICENSE`。
