# Changelog

All notable changes to mio-cua are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/). `Unreleased` holds in-progress
work; released sections are tagged on `master`.

---

## [Unreleased]

### Added

- **依赖**：`numpy>=1.24` 加入核心依赖（`perception/quality.py` 视觉兜底与测试需要）。
- **Phase 3 — 真实轨迹录制 / Replay / 失败归因（spec §5-§30）**：
  - `evaluation/schema.py` — 权威数据模型（stdlib-only，避免循环依赖）：`Trace`/`TraceEvent`/`ObservationSnapshot`/`BeliefSnapshot`/`PlanSnapshot`/`ActionRecord`/`VerificationRecord`/`ProgressRecord`/`RecoveryRecord`/`FailureAttribution`/`PlanComparison`/`BenchmarkResult`/`TraceRedactor`，统一 `to_dict`/`from_dict` 与 `schema_version=1`。
  - `evaluation/attribution.py` — 规则式失败归因 `FailureAttributor.classify(trace)`，按证据优先级（直接错误 > 动作结果 > 校验 > 观察 > 规划 > 启发）将失败归入 PERCEPTION/PLANNER/ACTION/ENVIRONMENT/VERIFICATION/UNKNOWN，绝不把"最后一个异常"当作根因。
  - `evaluation/recorder.py` — `RuntimeEventSink` 协议 + 事件驱动 `Recorder`（把运行时对象转成冻结快照后收集为 `Trace`）+ `JSONLTraceStore`（`<base>/<date>/<task>/trace.jsonl` + `metadata.json`，失败时自动归因）。
  - `evaluation/replay.py` — `ReplayEngine`（确定性重放重建状态转移并自动归因；planner 模式用 `compare_plans` 比对规划差异；live 模式显式禁用，绝不触发真实输入）、`ReplayOutcome`、`compare_plans`。
  - `evaluation/benchmark.py` — `benchmark(traces)` 聚合 `BenchmarkResult`（任务成功率、失败分布、恢复成功率、平均步数/恢复次数、步成功率）。
  - `runtime/loop.py`（`AgentLoopV2.run`）+ `agent/loop.py` — 接入运行时事件总线：`event_sinks`/`add_event_sink()`/`emit()`，零默认副作用（无 sink 时为 no-op），全链路发出 task_started / observation / belief_updated / plan_created / action_started / action_completed / verification / progress / recovery_started / recovery_completed / error / task_completed|task_failed。
  - `evaluation/__init__.py` — 导出上述 Phase 3 公共 API。
  - **真实场景录制桥接** — `mio-cua run "<任务>" --record` 现在把 Phase 3 接到**真实运行链路**：强制 `runtime_v2=True`（v2 事件总线）、把 `Recorder` 作为 `event_sinks` 挂到 `AgentLoopV2`，跑完自动落盘 `Trace`（`<artifact_dir>/traces/<date>/<task>/trace.jsonl` + `metadata.json`）并出一份失败归因报告。真实链路使用 `Perception()`（真截图+定位）与 `InputController()`（真键鼠），因此本机跑真实任务即可录下真轨迹。`agent_factory.Agent.run(task, record=True)` 暴露 `last_recorder` / `last_trace_dir` 供下游重放/归因/基准复用。新增 `test_phase3_record_integration.py` 用脚本化 planner/感知/控制器确定性验证该桥接（无需桌面或 LLM）。
- **去模型化 — 执行边界确定性层（回应"mio-cua 不应只是 LLM 薄封装"）**：把"大模型不会稳定做的事"工程化为确定性能力，让 A/B 实验（裸模型 vs mio-cua）有真实可开关变量。
  - `automation/grounding.py`（新增）— `Grounder`：执行前用**实时 UIA 树**（`uia.get_elements`）重新匹配模型给的 `element_id`→真实 bbox，校验 visible/enabled、hit-test 点击点落在活动窗口内，返回实时安全坐标；模型给裸 `x/y` 时做 hit-test 拒绝"点空/点错窗口"。实时源不可读时优雅降级到感知缓存坐标（旧行为），而非每击必败。win32/pywinauto 延迟导入，模块导入不依赖桌面。
  - `automation/input_controller.py` — `InputController` 增加可选 `grounder` 参数（`grounder=None` 时行为完全不变，向后兼容）；`element_id`/`x/y` 解析优先走 `Grounder.resolve`，落地失败抛 `GroundingError`（被循环当作 retryable → 触发恢复）。
  - `agent_factory.py` — `runtime_v2` 路径构造 `InputController(grounder=Grounder())`；`runtime/loop.py` 主感知后设 `self.controller.current_observation = obs` 供 grounding 取参考观察。
  - `runtime/recovery.py` — 新增 `recover_actions()` / `apply_recovery()`：**确定性恢复**，已知失败模式直接执行动作而非求 LLM 重规划——`context_menu→key(esc)`、`focus_lost`/`context_mismatch→focus_window(target)`、`target_invisible→scroll(down)`、`scroll_no_progress→reverse scroll`（stall≥2 且有搜索框时让位给 planner 提示）。`runtime/loop.py` 三个失败分支（context_mismatch / target_invisible / scroll_no_progress）先 `apply_recovery` 再重规划。
  - 新增测试 `test_phase3_grounding.py`（10 项：实时匹配/漂移取实时坐标/不可见拒绝/点空拒绝/越窗拒绝/降级）与 `test_phase3_recovery_deterministic.py`（8 项：各失败模式返回正确确定性动作、apply_recovery 经 registry 执行）。
- **实验工具 — 真实桌面 A/B/C/D 验证装置（让去模型化层有可证伪证据，不声称任何成功率）**：
  - `config.DEFAULTS` 增 `enable_grounding / enable_verification / enable_recovery`（默认 True，向后兼容）；`RecoveryManager(enabled=)` 集中 no-op；`loop.py` 按开关守卫 recovery/verification 调用点。A/B/C/D 映射：A=runtime_v1 裸执行；B=+Grounding；C=+Verification；D=+Recovery。
  - `experiments/real_sweep.py` — 4 版本 × N 次真实微信"搜索兴蓉打开聊天"，经 event sink + trajectory 解析收集 6 指标（任务成功率/错误点击率/目标定位成功率/Verification 误判率/Recovery 成功率/平均步数），输出 `results/real_sweep.csv`；`--dry-run` 验证矩阵无需桌面。`OPENAI_API_KEY` 与"微信需打开"前置检查。
  - `experiments/mechanism_proof.py` — 驱动**真实** `Grounder`/`RecoveryManager` 的机制验证（UI 漂移下裸坐标 0/20 vs Grounding 20/20；context_menu 卡死 vs 确定性 Esc 20/20），证明机制成立而非真实成功率提升。
  - `experiments/analyze_sweep.py` — 读 `real_sweep.csv` 出 A/B/C/D 六指标表 + 逐层增量（B−A/C−B/D−C）+ 倾向性判定（对照 `40%→55%→62%→75%` helps 与 `40%→42%→43%→44%` no-op）；`--selftest` 用合成数据验证输出形态（明确标注非真实结果）。纯实验工具，不触碰 agent 架构。

### Fixed

- `perception/quality.py` — `assess_quality(None)` 现在安全返回"无场景图"报告，而非 `AttributeError`；修复 Agent 循环在无 `scene` 的观察（如确定性 simulation 测试）上直接 FAIL 的问题。

### Docs

- **README 重写（中文，实测指标）**：纠正「32 工具」为实测 **36**；更正 Quick Start 的 `pip install mio-cua` 为源码安装（PyPI 尚未发布）；补全 `history` CLI 子命令、`MIO_CUA_*` 环境变量、A/B/C/D 实验层开关与 Phase 3 可观测性说明。
- **MCP.md 工具表补全**：新增 `mio_discover` / `mio_extract` / `mio_validate` / `mio_report` 四个 workflow MVP 工具，工具计数更新为 36。
- `mcp_server.py` — `mio_kill_process` 在 `taskkill` 失败时不再因 `e.stderr` 为 `None`（GBK 输出解码失败）而崩溃；改为按字节捕获并以 `utf-8/replace` 解码，异常路径返回结构化错误字符串。
- **Phase 3 回归修复（均由新增测试捕获）**：
  - `evaluation/attribution.py` — 补上 `classify()` 缺失的 `_goal_context(trace)` 方法（原引用未定义会 `AttributeError`）；补 `import logging`。
  - `evaluation/recorder.py` — 补 `import logging`；`Recorder._start()` 修复 `target_context` 取值优先级（此前总会从不存在的 `task` 键读空值而覆盖真实 `target_context`）；`JSONLTraceStore._load_dir()` 不再把 JSONL 行预转为 `TraceEvent` 后又交给 `Trace.from_dict` 二次转换（导致 `AttributeError`）。
  - `evaluation/replay.py` — `compare_plans()` 在 `parameters` 缺省时正确回退为 `{}`（此前 `None` 触发 `TypeError`）；离线重放绝不触发真实输入。
  - `evaluation/schema.py` — `_from_value()` 还原 `tuple` 类型（如 `ObservationSnapshot.screen_size`），避免 JSON 往返后元组退化成列表。

## [0.3.0] - 2026-08-22

### Added

- **文件内容工具** — 新增 `read_file` / `write_file` / `search_files` 三个确定性文件工具（零外部 SDK，仅标准库）：
  - `read_file(path, max_chars=2000)` 读取文本文件，超长截断并提示总数，二进制文件 fail（retryable）；上限钳制 100k。
  - `write_file(path, content, mode, allow_overwrite)` 支持 `create`（仅新建，拒绝覆盖）/`append`（追加，缺则新建）/`write`（覆盖，仅 `allow_overwrite=True`）；自动创建父目录。
  - `search_files(path, name, ext, pattern, max_results=50)` 递归搜索，`name`/`ext`/`pattern` 三过滤器 AND 组合，前 `limit` 条入结果、其余计 `more` 并提示 `...and N more`。
  - Agent / builtin / MCP 三通道注册；MCP 新增 `mio_read_file` / `mio_write_file` / `mio_search_files`。
- **文本选择能力** — 新增 `clipboard_get` / `clipboard_set` / `drag` / `select_element`（32 tools）：
  - `clipboard_get` 结构化返回 `{"text","has_text","length"}`，空剪贴板视为 success，OpenClipboard 失败才 retryable。
  - `clipboard_set(text)` 写入剪贴板，配合 `ctrl+v` 快速粘贴长文本。
  - `drag(x1,y1,x2,y2,element_id)`  primitive 拖拽；`element_id` 解析为 bbox 内缩（left+2 → right-2，mid-height），同时兼容 `obs.scene.nodes` 回退（OmniParser）。
  - `select_element(element_id)` composite 工具，基于 `drag` 横向拖选单行文本；Agent 侧闭环 `select → ctrl+c → clipboard_get` 校验。
  - `mio_cua/tools/{clipboard,drag,selection}.py` 新模块；`mcp_server.py` 薄包装重构，新增 `mio_select_element` / `mio_drag` / `mio_clipboard_*`。

### Fixed

- `tools/launch.py` — 裸域 URL（如 `example.com`）自动补 `https://` 解析到浏览器，避免被当成本地文件路径。
- `tools/selection.py` / `tools/drag.py` — `element_id` 解析增加 `scene.nodes` 回退，兼容 OmniParser 纯视觉控件 id 漂移。
- `tools/clipboard.py` — `OpenClipboard` 异常安全（try/finally 保证 CloseClipboard）。

### Changed

- `mcp_server.py: mio_drag` — 坐标直传时跳过 `Perception().observe()`，降低首帧开销（`perf: skip observe in coords-only mio_drag`）。

## [0.2.0] - 2026-08-15

### Added

- **Multi-step planner batching** — up to 3 tightly-related actions per plan,
  each re-verified against a fresh lightweight (OCR-only) observation before the
  next runs. Verification failure aborts the whole batch and replans with a
  GUIDANCE hint. Config: `batch_limit` (default 3), `batch_verify` (default True;
  `False` restores one-action-per-observation).
- **High-risk action confirmation** — delete / overwrite / kill_process /
  close_window now require an on-screen Yes/No confirmation before running;
  denial returns `retryable=False` (never retried) and timeout auto-denies
  (fail-closed). Disable with `MIO_CUA_CONFIRM_OFF=1`. Applies to the agent
  tool registry (schema `risk: "high"` + name-based fallback) and the MCP tools
  `mio_kill_process` / `mio_close_window`.
- **Screenshot → YAML scenario** — `mio-cua gen-scenario --image <png> | --capture`
  turns a real desktop screenshot into a YAML scenario (static element list);
  `mio-cua run "task" --simulate-scenario <scene.yaml>` replays it offline through
  the loop with no real input.
- **`mio_cua_GPU=0`** — forces OCR and layout-regions to CPU so onnxruntime /
  DirectML sessions don't run concurrently and spike VRAM.
- Promo assets (`promo/`), blog posts (`blog/`), marketing/growth docs, MIT
  LICENSE, and MCP Registry repository metadata.

### Fixed

- `scene/diff.py` — a curr node matched to a prev node by bbox but with a
  different id was falsely reported as "added" (int-vs-object comparison bug);
  broke scene diff accuracy whenever ids drifted.
- `agent/batch.py` OCR projection now reads observation *elements* (source
  "ocr") instead of scene nodes, so OCR glyphs folded into UIA nodes by
  NodeBuilder are not lost — full vs light frames diff symmetrically.
- `mio-cua run --simulate-scenario` now gives a friendly error on missing or
  malformed scenario YAML instead of a traceback; null element fields are
  tolerated.

## [0.1.5] - 2026-08-15

- MCP server sync to local sub-project repo; MCP Registry metadata.

## [0.1.2] - 2026-08-15

- OCR/vision made an optional extra.

## [0.1.1] - 2026-08-15

- README metadata, `server.json` for the MCP Registry.

[0.3.0]: https://github.com/mldlbs/mio-cua/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/mldlbs/mio-cua/compare/0.1.5...0.2.0
[0.1.5]: https://github.com/mldlbs/mio-cua/compare/0.1.2...0.1.5
[0.1.2]: https://github.com/mldlbs/mio-cua/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/mldlbs/mio-cua/compare/init...0.1.1
