# 多步 Planner 批量 + 实时复核 — 设计文档

> 日期：2026-08-15
> 状态：已批准（子项目 1 of 3）
> 所属：mio-cua v0.2 milestone

---

## 1. 背景与问题

当前 `mio_cua/agent/loop.py` 采用「一观察一动作」策略（loop.py:209-214）：

```python
# Only ONE action per observation: the screen changes after
# every action, so subsequent actions in the same plan were
# decided against a stale scene. Re-observe + replan first.
if i + 1 < len(plan.actions):
    break
```

`Planner.plan()` 已经能返回多 action 的 `Plan`，但 loop 故意只执行第一个，然后重新
observe + 重新 plan。这保证了每步决策都基于新鲜屏幕，但代价是**每次动作都要一次 LLM
往返**，跨应用/多步任务（如逐位输入数字）尤其低效。

**目标**：一个 plan 内最多连续执行 3 个动作，每个动作执行后做一次**轻量实时验证**
（expected 优先 + Scene Diff 回退）；验证失败立即中止整批并重新 plan。在保留「动作
永远基于新鲜屏幕」的前提下，把 LLM 往返从每动作一次降到每批一次。

## 2. 决策摘要（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 执行策略 | 批量 + 每步验证 |
| 批次上限 | 一个 plan 内最多连续 3 个动作，然后强制重新 plan |
| 验证标准 | expected（ExpectedVerifier）优先；无 expected 回退到 Scene Diff；非屏幕动作跳过 |
| 中途失败处置 | 任一 action 失败或验证不通过 → 整批中止，立即重新 plan（recover 逻辑继续生效） |
| 验证采集 | 轻量 observe（截图 + OCR + 轻量 scene，跳过 UIA/OmniParser/regions） |

## 3. 架构与组件

### 3.1 配置新增（`mio_cua/config.py`）

```python
DEFAULTS = {
    ...
    "batch_limit": 3,      # 一个 plan 内最多连续执行的动作数
    "batch_verify": True,  # 批次内每步做轻量验证；关闭则退化为「一观察一动作」
}
```

`batch_limit` 语义：**非终止动作**（非 success/fail）在单个 plan 内最多连续执行的个数。
`batch_verify=False` 时，即使 `plan.actions` 有多个动作，loop 仍回到旧行为（每观察只跑一个）。

### 3.2 轻量观察（`mio_cua/perception/perception.py`）

新增方法：

```python
def observe_light(self) -> Observation:
    """OCR-only observation for in-batch verification.

    Skips UIA, OmniParser web controls and layout regions -- the two model
    layers are the expensive part. Returns a scene built from OCR text nodes
    only, with no screenshot artifact and no SceneMemory push.
    """
```

- 只做：`get_active_window_rect` + `capture_rect` + `ocr.get_elements` + `build_scene`
- 不做：UIA、OmniParser、regions、screenshot 保存
- `screenshot_path=None`，避免污染审计留痕（审计截图仍由完整 observe 产生）

### 3.3 批次验证模块（新文件 `mio_cua/agent/batch.py`）

```python
VISIBLE_TYPES = ("click", "type", "key", "scroll")

def verify_action(prev_obs, curr_obs, action, expected) -> tuple[bool, str]:
    """Verify an action's on-screen effect between two observations.

    Returns (ok, detail). Decision order:
    1. expected (from affordance, e.g. {'display': True}) -> ExpectedVerifier
    2. else if action.type in VISIBLE_TYPES -> OCR-only Scene Diff (any change = pass)
    3. else (wait/launch/move_mouse/fs tools/success/fail) -> pass, "no visible expectation"
    """
```

关键点：

- **expected 优先**：复用 `ExpectedVerifier`（`mio_cua/agent/expected.py`），它已处理
  `display` 期望（`True` = 应变化，`unchanged` = 应不变）。
- **diff 回退**：对前后两帧做 **OCR-only 投影**再 diff。因为轻量 scene 只含 OCR 节点，
  若直接用 `compute_diff(prev_full, curr_light)` 会把 prev 中 UIA/OmniParser 节点误判为
  "removed"，导致永远"有变化"。因此 diff 前把两帧都投影到 OCR-only（取 `source == "ocr"`
  的节点），用 `mio_cua.scene.diff.diff` 比较。
- **非可见动作跳过**：wait / launch / move_mouse / screenshot / fs 工具 / success / fail
  不要求屏幕变化，直接通过。

### 3.4 Loop 改造（`mio_cua/agent/loop.py`）

批次执行逻辑（替换当前 `for i, action in enumerate(plan.actions)` 内层循环）。注意两个
独立变量：

- `prev`（外层）：完整观察基线，外层循环底部 `prev = obs` 维护，供下轮 `compute_diff`。
- `light_base`（批内）：轻量观察基线，批内每步验证后更新为 `light`，供 `verify_action`。

```
batch_executed = 0
light_base = obs                      # 批内验证基线 = 本 plan 决策所用的帧
for i, action in enumerate(plan.actions):
    if batch_executed >= batch_limit:     # 到达批次上限（仅约束非终止动作）
        break                             # -> 外层重新 observe + plan
    if safety.should_stop():
        break

    result = registry.call(action.type, action.params, ctx)  # 现有 recover 包装
    ...现有失败处理（recover / history / artifact / record_step）...
    if not result.success:
        break                             # 失败 -> 整批中止（现有 recover 已尝试）
    batch_executed += 1

    if action.type == "success":          # 终止动作
        ...现有 _unconfirmed_edit 守卫...
        finished_status = "SUCCESS"; break
    if action.type == "fail":
        finished_status = "FAIL"; break

    # 捕获期望（仅 click+element_id 时非 None）；下决定是否批内验证
    expected = None
    if action.type == "click":
        expected = self._capture_expected(obs, action)   # (node_id, expected, scene)

    has_successor = (i + 1 < len(plan.actions)) and (batch_executed < batch_limit)
    if not has_successor or not config.batch_verify:
        # 批次末尾或关闭验证：交给下一次完整观察的 _pending_verify 机制
        if expected is not None:
            self._pending_verify = expected
        break

    # --- 批内每步轻量验证（此动作不再设 _pending_verify，避免二次验证） ---
    light = self.perception.observe_light()
    self.controller.current_observation = light           # 下个 action 的 element_id 用最新帧解析
    exp = expected[1] if expected else None
    ok, detail = verify_action(light_base, light, action, exp)
    if not ok:
        if self.history is not None:
            self.history.record(action.id, action.type, False, f"verify: {detail}")
        self._batch_failed = detail                       # 下轮 plan 注入 GUIDANCE
        break                                             # 整批中止 -> 重新 plan
    light_base = light
```

`_batch_failed` 在 `run()` 开头初始化为 `None`，每个外层迭代开始时重置。

关键点：

- **批次上限只约束非终止动作**：`success`/`fail` 立即 break，不占用 batch_limit。
- **防重复验证**：批内每步验证过的动作**不再设置 `_pending_verify`**（否则下一次完整
  观察会再验一次，产生冗余 VERIFICATION hint）。只有批次**末尾动作**才设置
  `_pending_verify`，由下一次完整观察验证——保持与现有 hint 机制一致。
- **expected 来源**：沿用现有 `_capture_expected(obs, action)`（从 scene.affordance 取
  `expected`），仅对 `click` 且带 `element_id` 时有效。`verify_action` 的 `expected`
  参数由 loop 传入；为 None 时走 diff 回退。
- **失败 hint 注入**：下轮 `hints` 列表追加一条
  `GUIDANCE: the last batch was aborted because <detail>; re-inspect the screen and pick
  a fresh action, do NOT blindly repeat.`
- **history 守卫**：`self.history` 可能为 None（现有代码已用 `if self.history is not None` 守卫），批内记录失败也加守卫。

### 3.5 Prompt 更新（`mio_cua/prompts/system.txt`）

将第 26 行：

```
- Do one meaningful action per step, then check the result and continue. Do not repeat the same action twice if it worked.
```

改为（允许紧密动作批处理）：

```
- You may issue up to 3 closely-related actions in one plan when they are a tight sequence
  (e.g. typing a multi-digit number digit by digit). Each action is re-verified against the
  screen before the next runs. Do not repeat the same action twice if it worked.
```

## 4. 数据流

```
完整 observe ──> plan（LLM 返回 ≤ batch_limit 个动作）
                    │
                    ├── action1 执行 ──> observe_light ──> verify_action ──> 通过 ──> light_base=light
                    │                        │
                    │                        └── 失败 ──> 整批中止，hint 注入，重新 plan
                    ├── action2 执行 ──> observe_light ──> verify_action ──> 通过 ──> light_base=light
                    │
                    ├── action3 执行 ──> batch 上限到达 ──> 退出，外层完整 observe + plan
                    └── success/fail ──> 终止任务
```

## 5. 错误处理与安全

- 任一 action 失败（recover 后仍失败）→ 整批中止，重新 plan（现有 recover 不受影响）。
- 验证失败 → 整批中止；失败信息进 history + hint，指导下一轮不盲目重试。
- 批次上限 + 现有 Safety（max_steps / timeout / F9）叠加生效，每动作仍 `record_step()`。
- 轻量 observe 不产审计截图；完整 observe 的逐动作截图留痕保持不变。
- `batch_verify=False` 或 `batch_limit<=1` 时行为与旧版完全一致（兼容开关）。

## 6. 测试

### 6.1 单元测试（`tests/unit/test_batch.py`）

- `verify_action`：
  - expected=True 且 display 变化 → (True, ...)
  - expected=True 且 display 未变 → (False, ...)
  - expected="unchanged" 且 display 未变 → (True, ...)
  - 无 expected、click、OCR 层有变化 → (True, ...)
  - 无 expected、click、OCR 层无变化 → (False, ...)
  - 非可见动作（wait/move_mouse）→ (True, ...) 且不依赖 diff
  - UIA 节点在 prev 出现、curr 消失但 OCR 层无变化 → (False, ...)（OCR 投影正确性）

### 6.2 集成测试（`tests/integration/test_loop_mock.py`）

- 更新 `test_loop_only_one_action_per_observation` → 语义改为「3 动作同批执行，
  批间各一次轻量验证，LLM 只调一次」
- 新增「plan 返回 4 个动作 → 前 3 个同批，第 4 个重新 plan」
- 新增「批内第 2 个动作验证失败 → 整批中止，history 含 verify 失败，重新 plan」
- 新增「batch_verify=False → 仍一观察一动作」
- 新增「批内 success 前先验证前一个动作」
- 新增「批内验证过的 click 不再设置 `_pending_verify`（避免二次验证）」

### 6.3 感知测试（`tests/unit/test_perception.py` 或新增）

- `observe_light()`：返回 OCR-only scene；monkeypatch 确认**不调用** UIA / OmniParser /
  regions；`screenshot_path is None`

## 7. 不在范围内（YAGNI）

- 回滚已执行的动作（用户未选择）。
- 跳过失败动作继续执行批内剩余（用户未选择）。
- LLM 自行声明批量数量（固定上限 3 更简单可靠）。
- 批内每步完整 observe（成本高，轻量足够）。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 轻量 OCR 验证误报（屏幕动画/光标导致 diff 有变化但动作无效） | 验证只用于「中止批次」而非判定成功；即使误通过，下个动作仍基于新观察执行，外层还有 no_change/repeat hint 兜底 |
| OCR 层 diff 太敏感（微小文本噪声） | diff 基于节点匹配（id + 最近 bbox），非像素级；只要求「有任何变化」 |
| 批次内 element_id 指向旧 scene | 每步轻量 observe 后更新 `controller.current_observation`，解析用最新帧；找不到就抛 retryable → recover → 中止批 |
| 兼容性 | `batch_verify=False` / `batch_limit<=1` 完全保留旧行为，回归可测 |
