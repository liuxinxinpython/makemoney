# A股K线分析工具

一个基于PyQt5开发的现代化股票分析应用程序，集成了高级技术分析算法和优雅的用户界面。

## ✨ 功能特性

### 📊 核心功能
- **股票数据可视化** - 基于TradingView图表的K线展示
- **大数据支持** - 支持4GB+ SQLite数据库，智能缓存机制
- **实时进度反馈** - 加载过程中显示进度条和状态信息

### 🎯 技术分析
- **基础波峰波谷检测** - 基于局部极值分析
- **高级波峰波谷检测** - 使用Savitzky-Golay滤波器和形态学操作
- **策略结果可视化** - 在图表上标记关键点位

### 🛠️ 数据管理
- **Excel/CSV导入** - 批量导入A股票历史数据
- **数据库操作** - SQLite数据库管理，支持增量和重建导入
- **数据缓存** - 智能股票列表缓存，提升加载速度

## 📦 依赖包

### 核心依赖
- `PyQt5` - 图形用户界面框架
- `pandas` - 数据处理和分析
- `numpy` - 数值计算
- `scipy` - 科学计算（Savitzky-Golay滤波）

### 可选依赖
- `akshare` - 实时股票数据获取
- `matplotlib` - 图表绘制（备用）

## 🚀 安装和运行

### 环境要求
- Python 3.8+
- Windows/Linux/macOS

### 安装步骤

1. **克隆项目**：
```bash
git clone <repository-url>
cd pyqt-stock-analysis
```

2. **创建虚拟环境**（推荐）：
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# 或
source venv/bin/activate  # Linux/macOS
```

3. **安装依赖**：
```bash
pip install PyQt5 pandas numpy scipy
# 可选：安装akshare用于实时数据
pip install akshare
```

4. **运行应用程序**：
```bash
python main.py
```

## 📁 项目架构

```
pyqt/
├── main.py                    # 应用程序入口
├── src/                       # 源代码目录
│   ├── data/                  # 数据处理模块
│   │   ├── __init__.py
│   │   ├── data_loader.py     # K线数据加载
│   │   ├── import_excel_to_sqlite.py  # 数据导入
│   │   ├── volume_price_selector.py   # 数据查询工具
│   │   ├── workers.py         # 后台工作线程
│   │   └── a_share_daily.db   # SQLite数据库
│   ├── displays/              # 显示管理模块
│   │   ├── __init__.py
│   │   ├── base.py            # 显示接口和数据结构
│   │   └── chart_display.py   # 图表显示实现
│   ├── rendering/             # 渲染引擎模块
│   │   ├── __init__.py
│   │   ├── render_utils.py    # HTML渲染工具
│   │   └── templates/         # 模板资源
│   │       └── tradingview_template.html
│   ├── strategies/            # 策略分析模块
│   │   ├── __init__.py
│   │   ├── wave_peaks_valleys.py        # 基础波峰波谷
│   │   └── advanced_wave_peaks_valleys.py  # 高级波峰波谷
│   └── main_ui.py             # 主用户界面
├── debug_wave_test.py         # 调试脚本
└── README.md                  # 项目文档
```

### 🏗️ 架构设计

#### 分层架构
- **数据层** (`data/`) - 数据访问和处理
- **业务层** (`strategies/`) - 技术分析算法
- **显示层** (`displays/`) - 结果展示管理
- **渲染层** (`rendering/`) - UI渲染和模板

#### 设计原则
- **单一职责** - 每个模块职责清晰
- **依赖倒置** - 通过接口解耦模块依赖
- **开闭原则** - 支持扩展新的策略和显示方式

## 📖 使用指南

### 基本操作

1. **启动应用** - 运行 `python main.py`
2. **选择数据库** - 使用"数据 > 选择数据库文件"
3. **导入数据** - 使用"数据 > 导入"导入Excel/CSV文件
4. **查看股票** - 在下拉列表中选择股票代码
5. **运行策略** - 使用"选股"菜单选择分析策略

### 策略分析

#### 基础波峰波谷检测
- 检测方法：局部极值分析
- 标记颜色：红色箭头（波峰）、绿色箭头（波谷）
- 适用场景：简单趋势分析

#### 高级波峰波谷检测
- 检测方法：Savitzky-Golay滤波 + 形态学操作
- 标记颜色：橙色箭头（波峰）、紫色箭头（波谷）
- 适用场景：复杂市场环境下的精确分析

### 数据导入

支持的文件格式：
- Excel文件 (`.xls`, `.xlsx`, `.xlsm`, `.xlsb`)
- CSV文件 (`.csv`)

导入模式：
- **追加模式** - 增量添加新数据
- **重建模式** - 重新创建表结构

## 🔧 开发指南

### 添加新策略

1. 在 `src/strategies/` 创建新策略文件
2. 继承基础策略类并实现 `scan_current_symbol` 方法
3. 在 `main_ui.py` 的 `_initialize_strategies` 中注册策略

### 添加新显示方式

1. 在 `src/displays/` 实现新的显示接口
2. 继承 `DisplayInterface` 并实现相关方法
3. 在显示管理器中注册新的显示器

### 自定义模板

修改 `src/rendering/templates/tradingview_template.html` 来自定义图表样式和布局。

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [PyQt5](https://pypi.org/project/PyQt5/) - 优秀的GUI框架
- [TradingView](https://www.tradingview.com/) - 图表库灵感来源
- [akshare](https://github.com/akfamily/akshare) - 金融数据接口