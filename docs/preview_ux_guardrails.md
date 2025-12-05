# 策略即时预览守护清单

## 1. 流程速查
1. **参数收集**：`StrategyWorkbenchPanel` 中的“即时预览”按钮调用 `_run_preview()`，按当前卡片策略 + 表单参数构造 `params`。
2. **控制器入口**：`StrategyWorkbenchController._run_workbench_preview()` 接收策略键与参数，创建 `StrategyContext`（`current_only=True`），并通过 `StrategyRegistry.run_strategy()` 执行策略。
3. **主图刷新**：策略返回后，通过 `KLineController.set_markers()` 暂存 `markers/overlays`，随后 `render_from_database()` 只加载蜡烛数据（主图不显示策略标记）。
4. **预览弹窗**：`render_echarts_preview()` 使用 `src/rendering/templates/echarts_preview.html`，将 `markers/overlays/strokes` 注入 ECharts 画布，实现独立的策略图示。
5. **日志反馈**：预览成功时状态栏展示策略返回的 `status_message`，并把焦点移回 `web_view`，便于继续观察。

## 2. 数据依赖
- **markers**：策略的逐点标记（买卖点、波峰谷），在预览模板中以 `candlestick + scatter/line` 叠加展示。
- **overlays**：区间/中枢等信息，用于 ECharts 自定义矩形；主图不再显示，只在预览存在。
- **extra_data.strokes**：策略可提供“笔/线段”路径，`render_echarts_preview` 会绘制线段图层。
- **instrument/candles**：`KLineController` 当前内存中的蜡烛和标的信息是预览模板的数据源，若切换标的未完成加载则无法预览。

## 3. 回归检查
| 编号 | 检查点 | 步骤 |
| --- | --- | --- |
| P1 | 预览弹窗可用 | 在策略工作台选择任一策略，点击“即时预览”，应弹出独立 ECharts 窗口且显示蜡烛 + 策略元素。 |
| P2 | 主图无标记 | 预览过程中查看主图，确认 TradingView 视图只含基础 K 线，无策略 markers/overlays。 |
| P3 | 日志输出 | 预览后查看状态栏/日志，确保 `status_message` 或错误信息被写入，调试时可在 JS Console 看到 ECharts 日志。 |
| P4 | 依赖完整 | 若缺失模板或渲染异常，应弹窗提示“渲染失败”，且不会让线程卡死。 |

手动测试脚本：
1. 启动应用 → 加载任意标的。
2. 打开策略工作台 → ZigZag 策略 → 即时预览。
3. 关闭弹窗再重复执行 3 次，确保没有残留线程/僵尸窗口。

## 4. 开发注意事项
- 不要在 `KLineController._render_chart()` 中默认渲染 `markers/overlays`，否则会破坏“主图纯行情 + 弹窗展示策略”的体验。
- 修改 `render_echarts_preview` 模板时保持 `markerPoints/zoneRects/strokeLines` 数据结构兼容；新增字段需提供回退逻辑。
- 若策略需要新增可视元素，应优先复用 `extra_data`，由弹窗读取；主图的 `DisplayManager` 仅做数据聚合。
- 引入新策略前确认其 `StrategyRunResult` 至少包含 markers 或 overlays，否则预览将为空。
- 当 UI 层或控制器重构时，确保 `_show_echarts_preview()` 仍在成功执行策略后被调用。

## 5. 自动化/脚本建议
- 可考虑添加一个轻量集成测试：模拟 `StrategyRunResult` → 调用 `render_echarts_preview()` → 验证生成的 HTML 包含期望 JSON 片段。
- 对关键 JS 模板启用 `npm prettier` 或 lint 检查，防止合并时出现语法错误导致弹窗空白。

> 若未来在主图中重新展示策略标记，请新增设置开关并默认保持现状，以免影响当前预览 UX。