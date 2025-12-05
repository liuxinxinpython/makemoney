# 策略选股（批量扫描）方案

## 目标
- 将现有“批量扫描”模块升级为“策略选股”，突出其产出——符合策略买点的股票列表。
- 保持策略工作台的即时预览体验，用于微调参数；选股流程用于批量筛选。
- 为后续回测与其它模块铺平接口，避免重复实现扫描逻辑。

## 现状速览
- **UI**：`StrategyWorkbenchPanel._build_scan_tab`（`src/ui/panels.py`）提供“批量扫描”标签页，包含股票池输入、日期范围、扫描按钮以及简单表格。
- **执行层**：`StrategyScanner`（`src/research/scanner.py`）同步遍历 `request.universe`，对每只股票调用 `StrategyRegistry.run_strategy`，以“标记数量”作为得分，缺少日期范围、并发、进度控制和导出能力。
- **数据模型**：`ScanRequest`/`ScanResult`（`src/research/models.py`）仅包含策略键、股票代号、得分、部分 metadata，没有“买入信号明细”字段。

## 需求拆分
1. **UX 统一**：在工作台中将“批量扫描”文案、按钮等统一为“策略选股”，突出结果列表可双击跳转主图。
2. **结果展示**：表格需展示每条入选记录的：
   - 股票/名称
   - 触发日期（entry_date）
   - 信号价格/收盘价（entry_price）
   - 策略得分或置信度
   - 备注（策略返回的状态、分型描述等）
3. **筛选与导出**：提供最少“复制代码列表”“导出 CSV”两个动作，便于进一步操作。
4. **异步扫描**：扫描期间允许更新进度、取消任务，避免阻塞 UI。
5. **接口契约**：策略需要能够返回“候选信号”列表而非仅 markers 数量，以便排序/展示。

## 设计方案
### 1. UI & 交互
- 将 `QTabWidget` 标签改名为“策略选股”，按钮改为“开始选股”，日志面板改为“扫描日志”。
- 表格列设计：`排名 | 股票 | 买入日期 | 买入价 | 得分 | 备注`。
- 新增工具栏：
  - “导出 CSV” 按钮：调用 `QFileDialog` 选择路径，将当前 `scan_results` 写出。
  - “复制代码” 按钮：把 `symbol` 或 `table_name` 列复制到剪贴板。
- 双击结果行：保持现有 `load_symbol_handler`，并在状态栏提示“已定位到 xxx，建议打开策略预览查看具体形态”。

### 2. 数据契约
- 扩展 `ScanResult`：
  - `entry_date: Optional[str]`
  - `entry_price: Optional[float]`
  - `confidence: Optional[float]`
  - `extra_signals: List[Dict[str, Any]]`（保存策略返回的原始信号，比如 markers）。
- 策略运行入口：
  - `StrategyRunResult.extra_data` 增加约定键 `scan_candidates`，格式：`[{"date": "2024-11-15", "price": 18.23, "score": 0.82, "note": "一买"}, ...]`。
  - `StrategyScanner` 读取该列表；若缺失则回退到现有 `markers` 统计。

### 3. 扫描管线
- 新增 `StrategyScanWorker(QtCore.QObject)`：
  - 接收 `ScanRequest`、`db_path`，在独立 `QThread` 中执行。
  - 逐标的运行策略，yield 结果，通过 `progress(symbol, index, total)` 信号反馈。
  - 支持 `cancel()`：在每轮前检查 `self._cancelled`。
- `StrategyScanner.run_async()`：
  - 负责启动线程、连接信号、在完成/取消时清理。
  - `StrategyWorkbenchPanel` 在扫描按钮点击时禁用按钮，显示进度，允许“取消”按钮。
- 排序逻辑：默认按 `confidence` 或 `score` 降序，可根据需求添加排序下拉框。

### 4. 持久化/导出
- 在 `StrategyWorkbenchPanel` 中实现：
  - `self.scan_export_button.clicked.connect(self._export_scan_results)`。
  - `_export_scan_results`：
    1. 如果 `scan_results` 为空提示用户。
    2. 通过 `csv.writer` 输出列头 + 各行数据。
- 复制功能：`QtWidgets.QApplication.clipboard().setText("\n".join(symbols))`。

### 5. Integration Notes
- 当前 `StrategyWorkbenchController` 通过 `StrategyRegistry` 注册策略；新数据契约要求策略作者在 `extra_data['scan_candidates']` 填写结构化信息。
- 若策略缺少该字段，`StrategyScanner` 将：
  1. 使用 `run_result.markers` 的最后一个标记时间作为 `entry_date`；
  2. 使用 `extra_data.get('last_close')` 或 0 作为 `entry_price`；
  3. `score = len(markers)`。
- DisplayManager 不需要改动；选股结果依旧通过 `load_symbol_handler` 进入 K 线图，用户可再点击“即时预览”查看细节。

## 实施步骤
1. **模型层**：更新 `ScanResult` dataclass，与策略返回的 `extra_data` 契约保持一致。
2. **执行层**：引入 `StrategyScanWorker` + 线程封装，`StrategyScanner.run_async` 提供 Promise/回调接口。
3. **UI 文案**：批量替换“批量扫描”→“策略选股”，按钮提示等保持一致。
4. **结果表格**：扩展列、填充值、支持双击跳转和排序。
5. **导出/复制**：实现 CSV/剪贴板动作并连接到工具栏。
6. **取消控制**：扫描过程中将按钮切换为“取消选股”，完成后还原。
7. **策略示例**：挑选 1–2 个策略在 `extra_data['scan_candidates']` 中填充示例数据，用于验证 UI。

## 后续展望
- 扫描完成后可直接触发回测请求，或把结果推送到自定义 watchlist。
- 与未来“回测模块”共用策略执行缓存，避免重复读取数据库。
- 在导出文件中记录策略参数，便于复现。
