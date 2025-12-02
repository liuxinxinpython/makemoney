# A股K线分析工具

一个基于 PyQt5 与 TradingView 嵌入式图表的现代化股票分析应用程序，专注于 ZigZag 波峰波谷策略，并内置策略研究工作台、批量扫描和轻量回测能力。

## ✨ 功能特性

### 📊 核心功能
- **股票数据可视化** - 使用 TradingView HTML 模板渲染交互式 K 线图
- **大数据支持** - 面向 4GB+ SQLite 数据库，配合智能缓存保障加载速度
- **实时进度反馈** - 数据导入、策略执行均显示进度条与状态提示

### 🎯 技术分析
- **ZigZag 波峰波谷检测** - 统一的 ZigZag 算法，支持自定义最小反转幅度
- **策略结果可视化** - 波峰/波谷、状态标签直接绘制在主图上
- **策略参数即改即用** - 通过工作台调整参数后即可触发即时预览

### 🧠 策略研究工作台
- **可停靠右侧面板** - 通过 `视图 > 显示策略工作台` 控制显示/隐藏
- **策略卡片区** - 展示描述、输入参数与默认配置
- **研究工具集** - 即时预览、批量扫描、历史回测三合一
- **与主图打通** - 预览/扫描的选中结果可回填到主界面

### 🛠️ 数据管理
- **Excel/CSV 导入器** - 支持全量或追加同步至 SQLite
- **数据库切换** - 即时更换目标数据库并刷新股票列表
- **缓存与并发** - 后台线程异步加载，避免 UI 卡顿

## 📦 依赖包

### 核心依赖
- `PyQt5` - 主窗体、菜单、Dock 窗口与线程管理
- `pandas` / `numpy` - 数据处理与指标计算
- `scipy` - ZigZag 策略使用的信号处理工具
- `akshare`（可选）- 若需补充行情，可选安装

## 🚀 安装和运行

### 环境要求
- Python 3.8+
- Windows / Linux / macOS（开发主要在 Windows 测试）

### 安装步骤
1. **克隆项目**
	```bash
	git clone <repository-url>
	cd pyqt-stock-analysis
	```
2. **创建虚拟环境（推荐）**
	```bash
	python -m venv venv
	venv\Scripts\activate  # Windows
	# 或
	source venv/bin/activate  # Linux/macOS
	```
3. **安装依赖**
	```bash
	pip install -r requirements.txt  # 如未提供可按“核心依赖”手动安装
	```
4. **运行应用**
	```bash
	python main.py
	```

## 📖 使用指南

### 基本操作
1. **启动程序**：运行 `python main.py`
2. **选择数据库**：`数据 > 选择数据库文件` 绑定目标 SQLite
3. **导入数据**：`数据 > 导入` 选择 Excel/CSV，支持追加或重建
4. **选择标的**：在主界面股票下拉框中选择股票代码
5. **运行策略**：`选股 > ZigZag波峰波谷` 触发一次性检测
6. **策略研究**：`视图 > 显示策略工作台` 打开右侧面板，使用即时预览/批量扫描/历史回测进一步分析

### 策略研究工作台
- **打开方式**：通过菜单或快捷按钮显示/隐藏 Dock
- **即时预览**：调整 ZigZag 参数后点击预览，结果直接绘制在主图
- **批量扫描**：指定股票池与参数，输出评分/备注列表，可双击定位
- **历史回测**：使用轻量回测引擎计算收益、回撤与胜率，辅助筛选

## 📁 项目架构

```
pyqt/
├── main.py                    # 应用入口
├── src/
│   ├── data/                  # 数据导入、加载与后台任务
│   ├── displays/              # 图表显示接口与实现
│   ├── rendering/             # TradingView 模板渲染工具
│   ├── research/              # 策略注册、扫描、回测与API模型
│   ├── strategies/            # ZigZag 策略实现（当前聚焦 zigzag_wave_peaks_valleys.py）
│   ├── ui/                    # 工作台等共享 UI 组件（`panels.py`）
│   └── main_ui.py             # 主窗口，负责菜单、Dock、策略注册
├── README.md
└── ...
```

## 🏗️ 架构设计
- **分层职责**：数据层（`data/`）、业务策略层（`strategies/`）、研究引擎（`research/`）、展示层（`displays/` + `rendering/`）
- **事件驱动**：后台线程通过信号/槽回传进度、状态与结果
- **策略注册中心**：`research.global_strategy_registry()` 统一暴露给菜单与工作台共享
- **可停靠 UI**：策略工作台作为 DockWidget，可随时隐藏或分离至独立窗口

## 🔬 策略分析

### ZigZag 波峰波谷
- **算法**：自定义反转百分比的 ZigZag 识别器
- **视觉呈现**：红色箭头（波峰）、绿色箭头（波谷），附加状态文本
- **工作台能力**：
  - *即时预览*：参数热更新，结果回写至主图
  - *批量扫描*：遍历股票池输出信号打分，支持备注与导出
  - *历史回测*：轻量级模拟，快速评估收益/回撤/胜率

## 🔧 开发指南

### 添加/扩展策略
1. 在 `src/strategies/` 中实现策略逻辑（可参考 `zigzag_wave_peaks_valleys.py`）
2. 在 `main_ui.py` 的 `_initialize_strategies` 中将策略接入主菜单或按钮
3. 调用 `research.global_strategy_registry().register(...)` 注册 `StrategyDefinition`
4. 若需让工作台识别策略，可在 `_register_workbench_strategies` 中添加定义，包括参数 schema、预览/扫描/回测入口

### 添加新显示方式
1. 在 `src/displays/` 中实现新的显示器，继承 `DisplayInterface`
2. 在主界面中注册该显示器并与渲染层打通

### 自定义模板
- 修改 `src/rendering/templates/tradingview_template.html` 可调整图表主题、指标、布局

## 📦 数据导入参考
- 支持 Excel (`.xls/.xlsx/.xlsm/.xlsb`) 与 CSV (`.csv`)
- **追加模式**：保留历史数据并新增
- **重建模式**：清空后重新导入，适合结构变化或全量更新

## 🤝 贡献指南
1. Fork 仓库
2. 创建分支 `git checkout -b feature/<name>`
3. 提交更改 `git commit -m "feat: <description>"`
4. 推送并发起 Pull Request

## 📄 许可证
项目遵循 MIT License，详见 `LICENSE`。

## 🙏 致谢
- TradingView 团队提供的优秀前端交互体验启发
- PyQt 社区贡献的高质量组件与教程

- [PyQt5](https://pypi.org/project/PyQt5/) - 优秀的GUI框架
- [TradingView](https://www.tradingview.com/) - 图表库灵感来源
- [akshare](https://github.com/akfamily/akshare) - 金融数据接口