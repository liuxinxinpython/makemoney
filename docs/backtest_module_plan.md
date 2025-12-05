# 回测模块规划

## 目标
- 将当前占位式 `BacktestEngine`（`src/research/backtest_engine.py`）升级为可复现真实交易逻辑的模块。
- 支持单标、股票池、全市场等不同范围的批量回测，沉淀为策略评估工具。
- 与“策略选股”共享策略执行结果、行情读取管线，避免重复计算。

> **实现进展（2025-12-06）**
> - `BacktestEngine` 已输出真实交易模拟：按策略 `extra_data['trades']` 生成持仓，支持最大持仓数量、单笔仓位比例、手续费与滑点假设。
> - `StrategyContext` 新增 `mode/start_date/end_date`，回测阶段以 `mode="backtest"` 调用策略，扫描/预览也明确模式。
> - 回测 UI 新增最大持仓、仓位比例、佣金、滑点配置，并展示交易明细表与 KPI。
> - 通过 `StrategyWorkbenchPanel` 可直接读取回测结果、查看每笔交易收益与胜率，便于快速调参与验证。

## 一、回测范围与调度
1. **运行范围**：
   - 单只标的：用于验证策略在当前图表上的历史盈亏。
   - 自定义股票池：与策略工作台中的股票池输入保持一致。
   - 全部数据库表：后台批量分析，适合夜间任务。
2. **时间轴**：
   - 默认使用用户界面选择的开始、结束日期。
   - 若为空，则自动对该标的可用历史全量回测，并在日志中提示。
3. **调度方式**：
   - UI 触发后在独立 `QThread` 中执行，实时推送进度。
   - 未来可挂接命令行/批处理入口，重用同一引擎类。

## 二、策略 API 设计
1. **扩展 `StrategyContext`**：
   - 新增 `mode` 字段（`"preview" | "scan" | "backtest"`），策略可根据模式决定输出。
   - 当 `mode="backtest"` 时，要求策略返回完整的买卖点序列而非单个 markers。
2. **`StrategyRunResult` 增强**：
   - 扩展 `extra_data` 约定：
     ```json
     {
       "trades": [
         {"entry_time": "2024-03-01", "entry_price": 12.3, "exit_time": "2024-04-05", "exit_price": 14.0, "size": 1.0, "reason": "二买"},
         ...
       ],
       "signals": [  // 历史逐烛信号，可供选股/可视化复用
         {"time": "2024-03-01", "type": "buy", "score": 0.8},
         ...
       ]
     }
     ```
   - 保持向后兼容：若策略仅返回 markers，回测引擎可按简单规则推导（例如固定持有 N 日或 trailing stop）。
3. **交易成本与仓位**：
   - `BacktestRequest` 新增字段：`commission_rate`、`slippage`、`position_size`（百分比或固定股数）。
   - 在 UI 中（`StrategyWorkbenchPanel._build_backtest_tab`）提供输入控件，默认 A 股常规费率（万 3）。

## 三、引擎工作流
1. **数据加载**：
   - 复用 `load_candles_from_sqlite` 或统一 `DataLoader`，按日期区间批量拉取收盘价、成交量等。
   - 对全市场任务使用分块加载，避免一次性占用内存。
2. **信号评估**：
   - 每个标的构造 `StrategyContext` (`mode="backtest"`)。
   - 调用策略，获取 `trades`/`signals`。若无 `trades`，则尝试根据 `signals` + 配置生成买卖对。
3. **交易执行**：
   - 对每笔交易计算：
     - 实际买入价 = `entry_price * (1 + slippage/2)` + 手续费。
     - 实际卖出价 = `exit_price * (1 - slippage/2)` - 手续费。
     - 仓位金额 = `initial_cash * position_size` 或固定数量。
   - 日度权益曲线：按交易发生日更新，若需要，可支持按 `signals` 重构逐日持仓。
   - 支持多仓位/重叠交易：初版可以限制同一时间只有一笔交易，后续再扩展。
4. **指标聚合**：
   - 必备：净利润、收益率、最大回撤、胜率、平均盈亏、夏普比率。
   - 可选：年化收益、最长回撤天数、交易次数、盈亏比、平均持仓天数。
   - 对于股票池/全市场，汇总：
     - 按标的统计成功率、累积 PnL。
     - 输出 Top 5/Bottom 5 标的，供 UI显示或导出。

## 四、结果展示与导出
1. **UI 输出**：
   - `StrategyWorkbenchPanel` 的「历史回测」页新增：
     - 交易列表表格（日期、标的、买价、卖价、PNL、备注）。
     - Equity Curve 简图（可先用 QChartView/Matplotlib 生成 PNG）。
   - KPI 卡片扩充：收益率、年化收益、交易数。
2. **导出**：
   - 导出 CSV：包含所有交易记录和核心指标。
   - 未来考虑导出 JSON，用于报告生成。
3. **日志**：
   - 回测过程中 `BacktestEngine.progress` 输出当前标的 + 阶段，例如“加载数据”“运行策略”“计算指标”。

## 五、与现有扫描逻辑的复用
1. **共享策略运行结果**：
   - `StrategyScanner` 与 `BacktestEngine` 均通过 `StrategyRegistry.run_strategy` 获取 `StrategyRunResult`。
   - 统一 `extra_data` 字段，如 `scan_candidates`、`trades`、`signals`，可以在选股与回测之间互相引用。
2. **结果缓存**：
   - 在批量选股后可缓存当日策略信号，回测时若参数一致，可直接使用缓存以节省数据库 IO。
   - 可引入简单的 `@lru_cache` 或基于表名/日期/参数的键值缓存。
3. **线程管理**：
   - 扫描与回测都使用 `QtCore.QThread` + Worker 模式，抽象出通用基类（带 progress/failed/cancelled 信号），简化维护。

## 六、实施优先级
1. **阶段 0 - 基础能力**：
   - 扩展 `BacktestRequest`、`StrategyRunResult`、`StrategyContext`。
   - 重写 `BacktestEngine` 主循环，支持真实 PnL 计算。
2. **阶段 1 - UI & 导出**：
   - 更新 `StrategyWorkbenchPanel` 回测页，新增控件与结果展示。
3. **阶段 2 - 策略适配**：
   - 为 1~2 个示例策略实现 `extra_data['trades']` 输出，验证引擎。
4. **阶段 3 - 共享优化**：
   - 引入缓存、批处理、日志规范等。

完成以上规划后，即可按阶段迭代实现，优先保证单标回测跑通，再逐步扩展。