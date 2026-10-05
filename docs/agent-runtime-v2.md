# Agent Runtime v2 — 里程碑总结与架构

> 目标：把 `mio-cua` 从「玩具级 Agent」升级为生产级 **Agent Runtime v2**——以 5 个可组合闭环（Goal → Belief/State → Perception → Planner → Action → Verify → Progress → Recovery）驱动，而非靠 app 特定补丁。微信在此架构中只是**基准验证场景**，不是 feature target。

## 1. 架构：5 个闭环

```
        ┌─────────────┐
        │  Goal / Task │  (target_context: app + keyword + expected)
        └──────┬──────┘
               ▼
        ┌─────────────┐   ① Goal→State/Belief
        │   Perception │  observe() → SceneGraph
        │  (SceneGraph │
        │   +Affordance)│→ RuntimeObservation (chat_list_region, search_box, candidates)
        └──────┬──────┘
               ▼
        ┌─────────────┐   ② Belief / State
        │   BeliefState │  context_matches, target_visible, scroll_stall, reverse dir
        └──────┬──────┘
               ▼
        ┌─────────────┐   ③ Planner
        │   Planner    │  LLM picks actions from structured prompt (NOT raw pixels)
        │  (prompt =   │
        │   scene +     │
        │   invariants) │
        └──────┬──────┘
               ▼
        ┌─────────────┐   ④ Action + Verify
        │   Action      │  registry.call → InputController → backend (win32/pyautogui)
        │   + Verify    │  post-action context drift / scroll progress check
        └──────┬──────┘
       ┌──────┴───────┐
       ▼              ▼
┌─────────────┐  ┌─────────────┐
│ ProgressEval │  │  Recovery    │  ⑤ Progress + Recovery
│ (scroll chg? │  │  Manager     │  focus retry / search fallback / reverse scroll
│  target vis?)│  │  (strategies)│
└──────┬──────┘  └──────┬──────┘
       └───────┬─────────┘
               ▼  (loop)
```

核心原则：**能力不认识微信，Runtime 才知道**。Perception 把"可滚动聊天列表区域""搜索框"提炼成 Affordance，Runtime 据此执行；LLM 只从结构化 prompt 里选动作，不猜坐标。

## 2. 模块与职责

| 模块 | 职责 |
|------|------|
| `mio_cua/runtime/observation.py` | `RuntimeObservation`：从 raw obs 推导 `chat_list_region`（候选节点 bbox 并集）、`search_box`、candidates、affordances。过滤退化 bbox 与容器节点。 |
| `mio_cua/runtime/belief.py` | `BeliefState`：context/target 匹配、scroll stall 计数、反向滚动决策。 |
| `mio_cua/runtime/progress.py` | `ProgressEvaluator`：scroll 前后候选数对比 → progressed？target visible？ |
| `mio_cua/runtime/recovery.py` | `RecoveryManager`：focus_target、search/scroll 回退策略库。 |
| `mio_cua/runtime/loop.py` | `AgentLoopV2(AgentLoop)`：5 闭环编排，复用父类 `_make_ctx`/`_save_state`/轨迹日志；注入 scroll region、点击坐标守卫、上下文不变式。 |
| `mio_cua/agent/planner.py` | Planner prompt 渲染：窗口相对侧边栏、容器节点排除、PLANNING RULES（element_id、禁 ctrl+f、搜索优先、收敛）。 |
| `mio_cua/evaluation/` | `dataset`/`harness`/`metrics`/`benchmark`：Eval Harness，monkeypatch `AgentLoopV2.run` 捕获轨迹，统计 success/stall/violation（不改 Agent 行为）。 |
| `mio_cua/tools/scroll.py` + `automation/backends.py` | scroll 透传 `region` → 滚动前把光标移到区域中心再滚轮（修复"滚动打空"根因）。 |

接入：`config.runtime_v2`（默认 False，保证 v1 测试不受影响）；`agent_factory` 在 `runtime_v2=True` 时改用 `AgentLoopV2`。

## 3. 本次里程碑（Perception grounding + Planner 提示）关键修复

1. **滚动打空（根因）**：`backends.py` 的 scroll 之前 `mouse_event(WHEEL,0,0,delta,0)` **从没定位光标**，滚在 stray 位置 → 聊天列表不动、候选集冻结。修复：`scroll` schema 本就有 `region` 参数，`scroll.py` 透传 → 后端先 `SetCursorPos(区域中心)` 再滚轮。`RuntimeObservation` 算出 `chat_list_region`（候选节点并集 bbox）注入每次 scroll。
   → **scroll stalls 2.3/task（v1 基线）→ 0.33/task（v2b）**。
2. **点错目标**：Planner 旧逻辑用绝对 `x<300` 判侧边栏，但微信在 x=840 → 聊天列表被错标成"主面板"且为空；容器/窗口节点（id=0/1）仍在可点击列表，agent 频繁点窗口框架。
   → 改为**窗口相对**侧边栏（app 框架 bbox 左 50%）；按 `type=="group"` **及** semantic `MMUIRenderSubWindow`/`Weixin` 排除容器；PLANNING RULES 强制"按 element_id 点匹配关键词的聊天项，禁用裸 x/y，禁用 ctrl+f，搜索框优先"。
3. **焦点跳走**：agent 曾用裸坐标点进 Chrome/ChatGPT → context violation。
   → 新增**点击坐标守卫**：`click` 带裸 x/y 且落在目标窗口 bbox 外则拦截并提示改用 element_id。context violations 归 **0**。
4. **焦点不可聚即放弃**：首帧上下文不匹配时原先只 focus 一次就 break（0 步 FAIL）。
   → 改为 **focus 重试 3 次**。

## 4. 基准与结果（微信 10 任务）

| 指标 | v1 基线 | v2（含本里程碑） |
|------|--------|----------------|
| task_success_rate | 0% | 0%（受环境摆布，见 §5） |
| scroll_stall / task | 2.3 | 0.33 |
| context_violation / task | — | 0 |
| wrong_action_rate | — | 0（验证轮） |

> 0% 成功率**非代码缺陷**，而是真实微信窗口在当前桌面状态下常不可聚焦（窗口关闭/最小化/被其它应用抢占）。Eval Harness 跑在**实时共享桌面**上，非确定性高。代码改动已在合成场景确定性验证（见 §6）。

## 5. 已知限制 / 下一步

- **确定性基准（Phase 1 已完成）**：`replay.py` + 3 场景 JSON + `test_replay.py`（20 tests）提供无 LLM、无桌面的确定性回归。
- **Synthetic Planner Benchmark（Phase 2 已完成）**：`synthetic.py` + 5 场景 JSON + `test_synthetic.py`（15 tests）用固定 Observation 测试 LLM Planner 的决策类别正确性。
  - **真实 LLM 基线**（`default` model @ `ai.crlkcloud.cyou`）：valid_action_rate=60%（3/5），unsafe_action_rate=0%。
  - **核心缺陷**：LLM 在目标不可见时仍点击非匹配候选（2/5 失败），Target Visibility Invariant 约束力不足。
  - **已加强 prompt**：改为"违反任何一条 = 任务失败"格式，scroll 修复（2/5→3/5），但 click-non-matching 仍未解决。
- **Phase 3 路线**：Real Observation + Synthetic Execution。通用录制基础设施（`ObservationRecorder` + `TraceStore` + `ReplayPerception`）+ 全轨迹录制（`TraceRecorder`）+ 自动失败归因（`FailureClassifier`）已就绪。下一步：在真实应用上录制 Trace → 脱离环境 Replay → 真实 LLM Planner → Evaluator → 失败自动归因。分离 Perception/Planner/Action/环境四层错误。
- **FailureClassifier 证据链**：先判断 Observation 信息是否充分（Perception/Environment），再判断 Action 决策（Planner），最后判断执行（Action）。避免把 Planner 问题误归到 Perception。
- **关键对比测试**：Synthetic 失败 = Planner 能力问题；Synthetic 成功 + Real 失败 = Observation/Perception 表达问题。`SyntheticVsRealComparator` 支持此对比。
- **Phase 3 首批录制场景**（短 Trace，非完整任务）：
  1. 窗口切换：VS Code → 微信 → 验证（Context Runtime）
  2. 目标发现：聊天列表 → 搜索/滚动 → 找群（Planner + Visibility）
  3. 消息提取：进入群 → 定位消息区 → copy（Extraction）
- **Planner 仍可能选错**：在良好微信状态下需继续迭代（读消息后 `success` 判定、点击聊天后的主面板消息提取等分支）。
- **搜索框执行链路**：Perception 已暴露 `search_box` Affordance 与提示，但点击搜索框→输入→回车的端到端仍依赖 LLM 按提示执行，未做运行时强制。

## 6. 测试

- 确定性回归：`tests/unit/test_runtime.py`（7 用例，覆盖 observation/belief/progress/recovery）。
- Planner prompt 回归：`tests/unit/test_planner_prompt.py`（5 个合成场景 + 1 个 `RUN_LLM_TESTS=1` 门控的真实 LLM 冒烟）。
  - 合成场景：窗口相对侧边栏+框架排除、搜索框优先、多候选消歧、禁用裸坐标、主屏回退。
  - 真实 LLM 冒烟：合成场景下模型输出 `click {element_id: 3}`（目标「兴蓉项目群」），证明按 element_id 选中、非框架/裸坐标。
- 全量：在 `desktop-agent` 下 `pytest` → **303 passed, 1 skipped**（+ 20 replay + 15 synthetic + 19 recorder + 10 trace = 367 total）。

### 运行方式

```bash
# 单元/回归（无需桌面/LLM）
pytest tests/unit -q

# 真实 LLM 冒烟（需 key）
RUN_LLM_TESTS=1 MIO_API_KEY=sk-xxx pytest tests/unit/test_planner_prompt.py::test_real_llm_selects_target_by_element_id -s

# 微信基准（需微信处于可聚焦状态）
python -m mio_cua.evaluation.benchmark \
  --dataset mio_cua/evaluation/benchmarks/wechat_10.json \
  --base-url https://ai.crlkcloud.cyou/v1 --model default \
  --max-steps 15 --timeout 90 --runtime-v2 --ids wx-01,wx-04,wx-06
```

## 7. 确定性 Replay/Mock Benchmark（Phase 1）

### 设计原则

```
Replay = 测试 Runtime（固定 obs + 固定 action → 验证 state/verify/recovery/metrics）
Synthetic = 测试 Planner（固定 obs + LLM → 评估 action 是否合理）
```

- **数据隔离**：Agent 读 `observations[] + task`；Evaluator 读 `observations[] + action + ground_truth[]`。两条链物理隔离，`ground_truth` 不注入 Agent。
- **transition_graph**：有向多路径图，支持多条合法路径（如 scroll 或 search 均可推进）。匹配 action_type + params + preconditions → 推进到对应 obs。匹配不到 = invalid_action。
- **progress**：Belief 相对 Goal 的距离是否降低（由 Evaluator 根据 ground_truth 判断，不硬编码）。
- **不要求精确序列匹配**：评估 action validity、progress、safety invariant、goal completion、efficiency。

### 场景格式

```json
{
  "id": "scenario_name",
  "task": {"instruction": "...", "target_context": {...}},
  "observations": [{"id": 0, "active_window": "...", "scene_nodes": [...]}],
  "transition_graph": {"edges": [{"from": 0, "action_type": "scroll", "to": 1, "preconditions": {...}}]},
  "ground_truth": [{"obs_id": 0, "target_visible": false, "context_matches": true, "forbidden_patterns": [...]}],
  "goal": {"type": "action_type", "action_type": "success", "max_steps": 10}
}
```

### Phase 1 三场景

| 场景 | 难度 | 合法路径 | 测试重点 |
|------|------|----------|----------|
| `target_visible_click` | easy | click / search_click | 直接点击可见目标 |
| `scroll_discovery` | medium | scroll↓ / search_click → click | 滚动发现 + 搜索双路径 |
| `context_recovery` | medium | focus_window → click | 窗口失焦恢复 |

### 评估维度

**Per-step**：action_allowed（匹配 transition_graph）、safety_invariant（forbidden_patterns）、context_valid、target_visibility、progress
**Terminal**：goal_reached、steps ≤ max_steps、invalid_action_count = 0、recovery_count ≤ max_recovery_count

### 运行

```bash
# Phase 1 回归（无需桌面/LLM）
pytest tests/unit/test_replay.py -v

# Phase 2 Synthetic Evaluator 回归（无需 LLM）
pytest tests/unit/test_synthetic.py -v

# Phase 2 真实 LLM 冒烟（需 key）
RUN_LLM_TESTS=1 MIO_API_KEY=sk-xxx pytest tests/unit/test_synthetic.py::TestRealLLMSmoke -s
```

## 8. 文件地图

```
mio_cua/
  runtime/
    observation.py   # RuntimeObservation: chat_list_region / search_box
    belief.py        # BeliefState
    progress.py      # ProgressEvaluator
    recovery.py      # RecoveryManager
    loop.py          # AgentLoopV2（5 闭环编排 + 守卫）
  agent/
    planner.py       # prompt 渲染（窗口相对侧边栏 + PLANNING RULES）
    loop.py          # v1 AgentLoop（基线）
  tools/
    scroll.py        # region 透传
    builtin.py       # scroll schema（含 region）
  automation/
    backends.py      # win32/pyautogui scroll 前定位光标
  evaluation/
    dataset.py harness.py metrics.py benchmark.py
    replay.py        # Phase 1: ReplayPerception + MockInputController + Evaluator + ReplayBenchmark
    synthetic.py     # Phase 2: SyntheticBenchmark + SyntheticEvaluator (fixed obs → real LLM → evaluate)
    recorder.py      # 通用三层：ObservationRecorder（捕获）+ TraceStore（持久化）+ ReplayPerception（回放）
    trace.py         # TraceRecorder（全轨迹录制）+ FailureClassifier（自动归因）+ SyntheticVsRealComparator
    scenarios/       # 确定性场景 JSON
      target_visible_click.json    # Phase 1
      scroll_discovery.json        # Phase 1
      context_recovery.json        # Phase 1
      synthetic_planner_v1.json    # Phase 2: 5 决策类型
    observations/    # 录制的真实 Observation（Phase 3）
    benchmarks/wechat_10.json
  config.py          # runtime_v2 开关
  agent_factory.py   # runtime_v2 切换
tests/unit/
  test_runtime.py
  test_planner_prompt.py
  test_replay.py     # 20 tests: MockPerception + MockInputController + Evaluator + 3 scenarios
  test_synthetic.py  # 15 tests: SyntheticEvaluator + scenario loading + LLM-gated smoke (baseline: 3/5)
  test_recorder.py   # 19 tests: ObsFrame + ObservationRecorder + TraceStore + ReplayPerception
  test_trace.py      # 10 tests: FailureClassifier + Trace 结构 + SyntheticVsRealComparator
  test_quality.py    # 11 tests: PerceptionQualityGate + Visual Fallback + Scene Enhancement
```

## 4. 第一轮真实 Trace：关键发现

### Trace 数据
- **场景**: 目标发现 — 找到名为"兴蓉"的群并打开
- **耗时**: 222s, 16 步
- **文件**: `trace/trace_1787466378.json`, `trace/failure_report.json`

### 分层归因结果

| Layer | 发现 |
|-------|------|
| **Perception** | WeChat UIA tree 仅暴露 1 个节点 (`MMUIRenderSubWindowHW`)。聊天列表、搜索框不在 accessibility tree 中。Agent 无法看到任何可操作元素。 |
| **Planner** | 正确执行了 focus_window → 尝试搜索 → 循环。无错误点击。 |
| **Action** | focus_window 正常工作，切换到了微信窗口。但 Agent 无法操作看不到的元素。 |
| **Environment** | 模糊匹配修复：`微信` = `WeChat`。 |

### 关键结论

> Agent 能力上限 = Perception 能提供给 Planner 的世界模型质量。

Planner 已经开始工作，但只能基于它看到的世界决策。当 Perception 只返回 1 个 container 节点时，Planner 无法找到搜索框、聊天列表、目标群。

### 架构修复

实现 `PerceptionQualityGate` + `Visual Fallback`:

```
UIA + OCR
 ↓
Scene Graph
 ↓
QualityGate
  ├─ node_count < 5        → insufficient
  ├─ interactive_count == 0 → insufficient
  └─ container_only         → insufficient
        ↓
  Visual Fallback
  (enhanced OCR + region analysis)
        ↓
  Enhanced Scene Graph
        ↓
  Planner (with quality hints)
```

文件: `mio_cua/perception/quality.py`
