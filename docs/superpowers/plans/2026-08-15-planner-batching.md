# 多步 Planner 批量 + 实时复核 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一个 plan 内最多连续执行 3 个动作，每个动作执行后用轻量观察（截图+OCR）实时验证屏幕确实变化，失败即中止整批重新 plan，从而把 LLM 往返从每动作一次降到每批一次。

**Architecture:** `loop.py` 内层动作循环改为批次执行：执行 action → 捕获 expected → 若还有后继动作则 `perception.observe_light()`（OCR-only scene）→ `verify_action()` 验证（expected 优先 / OCR 投影 Scene Diff 回退 / 非可见动作跳过）→ 通过则更新 `light_base` 继续下一动作，失败则整批中止并注入 GUIDANCE hint。新增 `mio_cua/agent/batch.py` 承载验证逻辑；`config.py` 新增 `batch_limit`/`batch_verify` 开关；`system.txt` 允许紧密动作批处理。

**Tech Stack:** Python 3.10+，pytest，现有 `ExpectedVerifier` / `scene.diff` / `build_scene`。

**Spec:** `docs/superpowers/specs/2026-08-15-planner-batching-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `mio_cua/config.py` | 新增 `batch_limit`、`batch_verify` 默认值 | Modify |
| `mio_cua/perception/perception.py` | 新增 `observe_light()`（OCR-only） | Modify |
| `mio_cua/agent/batch.py` | `verify_action()` + OCR 投影 diff | **Create** |
| `mio_cua/agent/loop.py` | 内层循环改批次执行 | Modify |
| `mio_cua/prompts/system.txt` | 允许 3 个紧密动作批处理 | Modify |
| `tests/unit/test_config.py` | batch 默认值/覆盖 | Modify |
| `tests/unit/test_perception.py` | `observe_light` 不调用 UIA/OmniParser | Modify |
| `tests/unit/test_batch.py` | `verify_action` 全分支 | **Create** |
| `tests/integration/test_loop_mock.py` | 批次语义集成测试 | Modify |

---

### Task 1: 配置新增 batch_limit / batch_verify

**Files:**
- Modify: `mio_cua/config.py:6-16`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_config.py` 末尾追加：

```python
def test_batch_defaults():
    cfg = AgentConfig()
    assert cfg.batch_limit == 3
    assert cfg.batch_verify is True


def test_batch_overrides():
    cfg = AgentConfig(batch_limit=1, batch_verify=False)
    assert cfg.batch_limit == 1
    assert cfg.batch_verify is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: 新增两个测试 FAIL（AttributeError: batch_limit）。

- [ ] **Step 3: 实现**

在 `mio_cua/config.py` 的 `DEFAULTS` 中追加（放在 `artifact_max_bytes` 之后）：

```python
    "batch_limit": 3,       # 一个 plan 内最多连续执行的非终止动作数
    "batch_verify": True,   # 批次内每步做轻量实时验证；False 退化为「一观察一动作」
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/config.py tests/unit/test_config.py
git commit -m "feat: add batch_limit/batch_verify config (planner batching)"
```

---

### Task 2: Perception.observe_light（OCR-only 轻量观察）

**Files:**
- Modify: `mio_cua/perception/perception.py:45-104`
- Test: `tests/unit/test_perception.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_perception.py` 末尾追加：

```python
def test_observe_light_skips_uia_and_web(monkeypatch, tmp_path):
    """observe_light must be OCR-only: no UIA, no OmniParser, no regions,
    and must not write a screenshot artifact."""
    import mio_cua.scene.omniparser as omni_mod

    calls = {"uia": 0, "omni": 0}

    class BoomUIA:
        def get_elements(self):
            calls["uia"] += 1
            raise AssertionError("observe_light must not call UIA")

    def boom_parse(img):
        calls["omni"] += 1
        raise AssertionError("observe_light must not call OmniParser")

    monkeypatch.setattr("mio_cua.perception.perception.capture_rect", _fake_capture)
    monkeypatch.setattr("mio_cua.perception.perception.ocr_module", _FakeOCR())
    monkeypatch.setattr("mio_cua.perception.perception.uia_module", BoomUIA())
    monkeypatch.setattr(omni_mod, "parse", boom_parse)
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window", lambda: "Calc"
    )
    monkeypatch.setattr(
        "mio_cua.perception.perception.get_active_window_rect",
        lambda: (100, 50, 300, 200),
    )

    p = Perception(screenshot_dir=str(tmp_path))
    obs = p.observe_light()

    assert obs.screenshot_path is None, "light observe must not write artifacts"
    assert calls["uia"] == 0
    assert calls["omni"] == 0
    scene = obs.scene
    assert scene is not None and scene.nodes
    assert all((n.source or "") == "ocr" for n in scene.nodes), \
        "light scene must be OCR-only"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_perception.py::test_observe_light_skips_uia_and_web -v`
Expected: FAIL（AttributeError: 'Perception' object has no attribute 'observe_light'）。

- [ ] **Step 3: 实现**

在 `mio_cua/perception/perception.py` 中 `observe()` 方法之后（`_build_scene` 之前）新增：

```python
    def observe_light(self) -> Observation:
        """OCR-only observation for in-batch verification.

        Skips UIA, OmniParser web controls and layout regions -- the expensive
        model layers. Returns a scene built from OCR text nodes only, with no
        screenshot artifact and no SceneMemory push.
        """
        try:
            rect = get_active_window_rect()
        except Exception as e:
            logger.debug("get_active_window_rect failed: %s", e, exc_info=True)
            rect = (0, 0, 0, 0)
        active_window = ""
        try:
            active_window = get_active_window()
        except Exception as e:
            logger.debug("get_active_window failed: %s", e, exc_info=True)
        img = capture_rect(rect)
        ocr_elements = []
        try:
            for e in ocr_module.get_elements(img):
                e.bbox = _shift_bbox(e.bbox, rect[0], rect[1])
                ocr_elements.append(e)
        except Exception as e:
            logger.debug("OCR extraction failed (light): %s", e, exc_info=True)
        scene = build_scene(ocr_elements, active_window)
        return Observation(
            screenshot_path=None,
            timestamp=time.time(),
            active_window=active_window,
            dpi_scale=self.dpi_scale,
            elements=ocr_elements,
            scene=scene,
        )
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_perception.py -v`
Expected: PASS（含既有 cache 测试）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/perception/perception.py tests/unit/test_perception.py
git commit -m "feat: add Perception.observe_light for in-batch verification"
```

---

### Task 3: batch.py verify_action（批次验证核心）

**Files:**
- Create: `mio_cua/agent/batch.py`
- Test: `tests/unit/test_batch.py`（Create）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_batch.py`：

```python
from mio_cua.agent.batch import verify_action
from mio_cua.models.action import Action
from mio_cua.models.observation import Observation
from mio_cua.models.element import Element
from mio_cua.scene import build_scene


def _ocr_els(*texts):
    return [Element(i, "ocr", text=t, bbox=(i * 60, 0, 50, 20))
            for i, t in enumerate(texts)]


def _uia_els(*texts):
    # ids/boxes offset so UIA elements never collide with OCR elements
    # (NodeBuilder would fold an overlapping OCR text into the UIA node).
    return [Element(i + 100, "uia", text=t, bbox=(i * 60 + 1000, 0, 50, 20))
            for i, t in enumerate(texts)]


def _obs(elements, window="Calc"):
    scene = build_scene(elements, active_window=window)
    return Observation(None, 1.0, window, 1.0, elements, scene=scene)


def _calc_scene(disp_text):
    els = [
        Element(0, "uia", text="7", role="button", bbox=(100, 300, 50, 30)),
        Element(1, "uia", text=disp_text, role="text", bbox=(100, 10, 400, 80)),
    ]
    scene = build_scene(els, active_window="Calculator")
    scene.display_ids = [1]
    return _obs(els, "Calculator"), scene


def _click():
    return Action(id="a-1", type="click", params={})


# --- expected 优先 ---

def test_expected_display_changed_ok():
    prev, prev_scene = _calc_scene("0")
    curr, curr_scene = _calc_scene("7")
    prev.scene = prev_scene
    curr.scene = curr_scene
    ok, detail = verify_action(prev, curr, _click(), {"display": True})
    assert ok is True
    assert "changed" in detail


def test_expected_display_unchanged_fails():
    prev, prev_scene = _calc_scene("0")
    curr, curr_scene = _calc_scene("0")
    prev.scene = prev_scene
    curr.scene = curr_scene
    ok, detail = verify_action(prev, curr, _click(), {"display": True})
    assert ok is False
    assert "did not change" in detail


def test_expected_unchanged_semantics_ok():
    prev, prev_scene = _calc_scene("12")
    curr, curr_scene = _calc_scene("12")
    prev.scene = prev_scene
    curr.scene = curr_scene
    ok, _ = verify_action(prev, curr, _click(), {"display": "unchanged"})
    assert ok is True


# --- diff 回退（OCR-only 投影） ---

def test_diff_fallback_change_detected():
    prev = _obs(_ocr_els("OK", "Cancel"))
    curr = _obs(_ocr_els("OK", "Cancel", "NewNode"))
    ok, detail = verify_action(prev, curr, _click(), None)
    assert ok is True
    assert "changed" in detail


def test_diff_fallback_no_change_fails():
    prev = _obs(_ocr_els("OK", "Cancel"))
    curr = _obs(_ocr_els("OK", "Cancel"))
    ok, detail = verify_action(prev, curr, _click(), None)
    assert ok is False
    assert "did not change" in detail


def test_ocr_projection_ignores_uia_noise():
    # prev has an extra UIA node; curr light frame is OCR-only. The OCR layer
    # is identical, so the action must NOT be considered "changed".
    prev = _obs(_ocr_els("OK") + _uia_els("ButtonX"))
    curr = _obs(_ocr_els("OK"))
    ok, detail = verify_action(prev, curr, _click(), None)
    assert ok is False
    assert "did not change" in detail


# --- 非可见动作跳过 ---

def test_non_visible_action_passes_without_diff():
    for typ in ("wait", "move_mouse", "launch", "screenshot", "make_dir"):
        a = Action(id="a-1", type=typ, params={})
        ok, detail = verify_action(
            _obs(_ocr_els("same")), _obs(_ocr_els("same")), a, None
        )
        assert ok is True, typ
        assert "no visible expectation" in detail
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_batch.py -v`
Expected: FAIL（ModuleNotFoundError: mio_cua.agent.batch）。

- [ ] **Step 3: 实现**

创建 `mio_cua/agent/batch.py`：

```python
"""Batch execution support: in-batch per-step screen verification.

A plan may contain up to ``batch_limit`` actions. The loop executes them
consecutively, but re-observes the screen (light: OCR only) after each one to
confirm the action actually changed the screen before running the next. This
preserves "one action, one perception" safety while amortizing LLM calls across
a batch.
"""

from mio_cua.agent.expected import ExpectedVerifier
from mio_cua.scene.diff import diff as scene_diff
from mio_cua.scene.graph import SceneGraph

# Action types whose purpose is to change the on-screen content. For these we
# require an observable screen change when no explicit ``expected`` is present.
VISIBLE_TYPES = ("click", "type", "key", "scroll")


def verify_action(prev_obs, curr_obs, action, expected):
    """Verify an action's on-screen effect between two observations.

    Returns ``(ok, detail)``. Decision order:

    1. ``expected`` (from an affordance, e.g. ``{'display': True}``) is
       verified with ``ExpectedVerifier`` -- this is the strongest signal.
    2. else, if ``action.type`` is a visible action, fall back to a diff of the
       OCR-only layer between the two frames (any change = pass).
    3. else (wait/launch/move_mouse/fs tools/...) -> pass, the action is not
       expected to change the screen.
    """
    if expected:
        prev_scene = getattr(prev_obs, "scene", None)
        curr_scene = getattr(curr_obs, "scene", None)
        if prev_scene is not None and curr_scene is not None:
            return ExpectedVerifier().verify(prev_scene, curr_scene, expected)
    if action.type not in VISIBLE_TYPES:
        return True, "no visible expectation"
    changes = _ocr_diff(prev_obs, curr_obs)
    if changes:
        return True, "screen changed: " + "; ".join(changes[:3])
    return False, "screen did not change after action"


def _ocr_diff(prev_obs, curr_obs):
    """Diff ONLY the OCR layer of two observations.

    Light observations carry OCR-only scenes. Comparing them against a full
    scene directly would misreport every UIA/OmniParser node as "removed", so
    both frames are projected to their OCR nodes before the scene diff runs.
    """
    prev_nodes = _ocr_nodes(prev_obs)
    curr_nodes = _ocr_nodes(curr_obs)
    if not prev_nodes and not curr_nodes:
        return []
    prev = SceneGraph(nodes=prev_nodes)
    curr = SceneGraph(nodes=curr_nodes)
    return [c.description for c in scene_diff(prev, curr)]


def _ocr_nodes(obs):
    scene = getattr(obs, "scene", None)
    if scene is None:
        return []
    return [n for n in scene.nodes if (n.source or "") == "ocr"]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_batch.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/agent/batch.py tests/unit/test_batch.py
git commit -m "feat: add verify_action for in-batch screen verification"
```

---

### Task 4: Loop 批次执行（核心改造）

**Files:**
- Modify: `mio_cua/agent/loop.py:98-239`
- Test: `tests/integration/test_loop_mock.py`

- [ ] **Step 1: 更新旧测试语义 + 写新失败测试**

在 `tests/integration/test_loop_mock.py` 顶部追加导入（`build_scene` 目前只被旧测试局部 import，新增测试需要它）：

```python
from mio_cua.agent.batch import verify_action
from mio_cua.config import AgentConfig
from mio_cua.scene import build_scene
```

**删除**旧测试 `test_loop_only_one_action_per_observation`（语义已被批次取代），并追加：

```python
def _changing_scene_obs(count):
    """OCR observation whose text reflects ``count`` (screen changing)."""
    els = [
        Element(0, "ocr", text="Calc", bbox=(10, 10, 40, 20)),
        Element(1, "ocr", text=str(count), bbox=(10, 50, 40, 20)),
    ]
    sc = build_scene(els, active_window="Calc")
    return Observation(None, 1.0, "Calc", 1.0, els, scene=sc)


class ChangingPerception:
    """Full observe() and light observe() both advance the on-screen counter."""

    def __init__(self):
        self.count = 0
        self.full = 0
        self.light = 0

    def _next(self):
        obs = _changing_scene_obs(self.count)
        self.count += 1
        return obs

    def observe(self):
        self.full += 1
        return self._next()

    def observe_light(self):
        self.light += 1
        return self._next()


def test_loop_batches_three_actions_one_plan():
    """3 clicks in one plan run in a single batch (1 full observe for planning,
    2 light observes between), then replan."""
    full_plan_calls = []

    class ThreeThenSuccess:
        def __init__(self):
            self.calls = 0

        def plan(self, task, obs, diff, tools, history=None, hints=None):
            full_plan_calls.append(obs)
            self.calls += 1
            if self.calls == 1:
                return Plan(actions=[Action("a-1", "click", {"x": 1}),
                                     Action("a-2", "click", {"x": 2}),
                                     Action("a-3", "click", {"x": 3})])
            return Plan(actions=[Action("a-4", "success", {"result": "done"})])

    registry = FakeRegistry()
    perception = ChangingPerception()
    loop = AgentLoop(
        perception=perception,
        planner=ThreeThenSuccess(),
        registry=registry,
        events=EventBus(),
        safety=FakeSafety(),
        config=AgentConfig(),  # batch_limit=3, batch_verify=True
    )
    result = loop.run(Task(instruction="click three times"))
    assert result.status == "SUCCESS"
    assert registry.names.count("click") == 3
    assert perception.full == 2, "1 full observe to plan + 1 to replan"
    assert perception.light == 2, "one light verify between the 3 clicks"
    assert len(full_plan_calls) == 2, "LLM planned exactly twice"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/integration/test_loop_mock.py::test_loop_batches_three_actions_one_plan -v`
Expected: FAIL（当前 loop 仍是「一观察一动作」，`registry.names.count("click") == 1`）。

- [ ] **Step 3: 实现 loop 批次执行**

在 `mio_cua/agent/loop.py`：

1. 顶部新增导入：
```python
from mio_cua.agent.batch import verify_action
```

2. `run()` 中，`self._recent_sigs` 初始化处（`_verifier` 之后）新增：
```python
            self._batch_failed = None
```

3. 外层 while 循环内 `finish_hint = self._completion_hint(no_change)` 之后、`if len(self._recent_sigs)...` 之前插入批次失败 hint：
```python
                if self._batch_failed:
                    hints.append("GUIDANCE: the last batch was aborted because "
                                 f"{self._batch_failed}; re-inspect the screen "
                                 "and pick a fresh action, do NOT blindly repeat.")
                    self._batch_failed = None
```

4. **替换**内层 `ctx = self._make_ctx(obs)` 之后到 `for i, action in enumerate(plan.actions):` 循环体的批次逻辑。将现有：

```python
                for i, action in enumerate(plan.actions):
                    if self.safety.should_stop():
                        break
                    self.events.publish(ActionStarted(action))
                    ctx.current_action_id = action.id
                    try:
                        result = self.registry.call(action.type, action.params, ctx)
                    except Exception as e:
                        result = ActionResult(action.id, success=False, message=str(e), retryable=True)
                    if not result.success and result.retryable and self.recover is not None:
                        result = self.recover(action, result, ctx)
                    if result.success and action.type == "click":
                        self._pending_verify = self._capture_expected(obs, action)
                    self._save_artifact(obs, action, result)
                    self.events.publish(ActionFinished(result))
                    if self.history is not None:
                        self.history.record(action.id, action.type, result.success, result.message)
                    self.safety.record_step()
                    steps += 1
                    if action.type not in ("success", "fail"):
                        sig = f"{action.type}({sorted(action.params.items())})"
                        if self._recent_sigs and self._recent_sigs[-1] == sig:
                            repeat_count += 1
                        else:
                            repeat_count = 1
                        self._recent_sigs.append(sig)
                        if repeat_count >= 6:
                            finished_status = "FAIL"
                            finished_summary = f"stuck: repeated {sig} {repeat_count} times with no effect"
                            break
                    if action.type == "success":
                        blocker = self._unconfirmed_edit()
                        if blocker:
                            # hard guard: an element_id-less type (rename box /
                            # filename field) was not confirmed with Enter, so a
                            # success() would claim an edit that never applied.
                            hints.append(blocker)
                            self._save_artifact(obs, action, result)
                            self.events.publish(ActionFinished(ActionResult(
                                action.id, False, blocker, retryable=True)))
                            if self.history is not None:
                                self.history.record(action.id, action.type, False, blocker)
                            self.safety.record_step()
                            steps += 1
                            continue
                        finished_status = "SUCCESS"
                        finished_summary = str(action.params.get("result", ""))
                        break
                    if action.type == "fail":
                        finished_status = "FAIL"
                        finished_summary = str(action.params.get("reason", ""))
                        break
                    # Only ONE action per observation: the screen changes after
                    # every action, so subsequent actions in the same plan were
                    # decided against a stale scene. Re-observe + replan first.
                    # (Terminal success/fail already broke above.)
                    if i + 1 < len(plan.actions):
                        break
```

替换为：

```python
                config_batch_limit = getattr(self.config, "batch_limit", 3) if self.config else 3
                config_batch_verify = getattr(self.config, "batch_verify", True) if self.config else True
                batch_executed = 0
                light_base = obs
                for i, action in enumerate(plan.actions):
                    if batch_executed >= config_batch_limit or self.safety.should_stop():
                        break
                    self.events.publish(ActionStarted(action))
                    ctx.current_action_id = action.id
                    try:
                        result = self.registry.call(action.type, action.params, ctx)
                    except Exception as e:
                        result = ActionResult(action.id, success=False, message=str(e), retryable=True)
                    if not result.success and result.retryable and self.recover is not None:
                        result = self.recover(action, result, ctx)
                    self._save_artifact(obs, action, result)
                    self.events.publish(ActionFinished(result))
                    if self.history is not None:
                        self.history.record(action.id, action.type, result.success, result.message)
                    self.safety.record_step()
                    steps += 1
                    if not result.success:
                        # action failed (recover exhausted) -> abort the whole batch
                        self._batch_failed = result.message or "action failed"
                        break
                    if action.type == "success":
                        blocker = self._unconfirmed_edit()
                        if blocker:
                            # hard guard: an element_id-less type (rename box /
                            # filename field) was not confirmed with Enter, so a
                            # success() would claim an edit that never applied.
                            hints.append(blocker)
                            self._save_artifact(obs, action, result)
                            self.events.publish(ActionFinished(ActionResult(
                                action.id, False, blocker, retryable=True)))
                            if self.history is not None:
                                self.history.record(action.id, action.type, False, blocker)
                            self.safety.record_step()
                            steps += 1
                            continue
                        finished_status = "SUCCESS"
                        finished_summary = str(action.params.get("result", ""))
                        break
                    if action.type == "fail":
                        finished_status = "FAIL"
                        finished_summary = str(action.params.get("reason", ""))
                        break
                    if action.type not in ("success", "fail"):
                        sig = f"{action.type}({sorted(action.params.items())})"
                        if self._recent_sigs and self._recent_sigs[-1] == sig:
                            repeat_count += 1
                        else:
                            repeat_count = 1
                        self._recent_sigs.append(sig)
                        if repeat_count >= 6:
                            finished_status = "FAIL"
                            finished_summary = f"stuck: repeated {sig} {repeat_count} times with no effect"
                            break
                    batch_executed += 1
                    # Capture the expected on-screen change (clicks with an
                    # element_id that maps to an affordance).
                    expected = None
                    if action.type == "click":
                        pending = self._capture_expected(obs, action)
                        expected = pending[1] if pending else None
                    light_observe = getattr(self.perception, "observe_light", None)
                    has_successor = (i + 1 < len(plan.actions)) and (batch_executed < config_batch_limit)
                    if not has_successor or not config_batch_verify or light_observe is None:
                        # Batch tail, verification disabled, or perception has no
                        # light observe: defer to the next full observation via the
                        # existing _pending_verify hint.
                        if action.type == "click" and pending is not None:
                            self._pending_verify = pending
                        break
                    # --- in-batch light verification (do NOT set _pending_verify) ---
                    light = light_observe()
                    self.controller.current_observation = light
                    ok, detail = verify_action(light_base, light, action, expected)
                    if not ok:
                        if self.history is not None:
                            self.history.record(action.id, action.type, False, f"verify: {detail}")
                        self._batch_failed = detail
                        break
                    light_base = light
```

5. 外层循环底部 `prev = obs`（保持全量观察基线，避免 OCR-only 帧污染下轮 diff）：

```python
                prev = obs
```

> **实现期修正（code review 发现）**：原方案计划 `prev = light_base`，但 light 帧是 OCR-only，
> 下轮 `compute_diff(prev, obs)` 会把全量帧的 UIA 节点全判为 "added" → diff 恒非空 →
> `no_change` 恒为 0，抑制 "screen did not change" 与 completion hint。故改回 `prev = obs`。
> `light_base` 仍仅用于批内 `verify_action` 链式验证。

> **实现期修正（code review 发现）**：批内每步 `self.controller.current_observation = light`
> 会让后续 `element_id` 动作解析到 OCR-only 帧（id 空间不同，可能点错/报 not found）。
> 已删除该行——controller 保持指向 plan 时的完整 `obs`（`_make_ctx` 设置）。
> 新增回归测试 `test_loop_batch_keeps_controller_on_plan_obs` 用 spy controller 断言
> 批内所有 execute 都看到同一个 plan-time obs。

> **实现期修正**：`pending` 提前初始化为 `None`，避免条件定义 + 短路引用的脆弱性。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/integration/test_loop_mock.py -v`
Expected: `test_loop_batches_three_actions_one_plan` PASS；其余既有测试仍 PASS（`FakePerception` 无 `observe_light` → loop 走 batch 末尾 break 分支，行为不变；`_loop()` 不传 config → `getattr(None,...,...)` 走默认）。

- [ ] **Step 5: 追加批次相关失败测试**

追加到 `tests/integration/test_loop_mock.py`：

```python
def test_loop_aborts_batch_on_verify_failure():
    """3 clicks planned; the 2nd inline verify fails (screen stops changing)
    -> whole batch aborted, history records a verify failure, then replan."""
    from mio_cua.memory.history import History

    plan_calls = []

    class ClickClickClickThenSuccess:
        def __init__(self):
            self.calls = 0

        def plan(self, task, obs, diff, tools, history=None, hints=None):
            plan_calls.append(hints or [])
            self.calls += 1
            if self.calls == 1:
                return Plan(actions=[Action("a-1", "click", {"x": 1}),
                                     Action("a-2", "click", {"x": 2}),
                                     Action("a-3", "click", {"x": 3})])
            return Plan(actions=[Action("a-4", "success", {"result": "done"})])

    class StopsChangingPerception(ChangingPerception):
        def _next(self):
            # full observe -> "0", every light observe after -> "1":
            # click1 ("0"->"1") passes, click2 ("1"->"1") fails verification.
            snap = min(self.count, 1)
            self.count += 1
            return _changing_scene_obs(snap)

    history = History()
    registry = FakeRegistry()
    loop = AgentLoop(
        perception=StopsChangingPerception(),
        planner=ClickClickClickThenSuccess(),
        registry=registry,
        events=EventBus(),
        safety=FakeSafety(),
        config=AgentConfig(),
        history=history,
    )
    result = loop.run(Task(instruction="click three times"))
    assert result.status == "SUCCESS"
    assert len(plan_calls) == 2, "batch aborted -> replanned"
    assert any("verify: " in e.get("message", "") for e in history.entries), \
        "verify failure must land in history"
    assert any("aborted because" in (h or "")
               for h in plan_calls[1]), "GUIDANCE hint must reach the replan"


def test_loop_batch_verify_disabled_one_action_per_obs():
    """batch_verify=False keeps the old one-action-per-observation behavior."""
    class BatchPerception(ChangingPerception):
        def observe_light(self):
            raise AssertionError("observe_light must not be called when batch_verify=False")

    class OneClickPerPlanThenSuccess:
        def __init__(self):
            self.calls = 0

        def plan(self, task, obs, diff, tools, history=None, hints=None):
            self.calls += 1
            if self.calls in (1, 2):
                return Plan(actions=[Action(f"a-{self.calls}", "click", {"x": self.calls})])
            return Plan(actions=[Action("a-3", "success", {"result": "done"})])

    registry = FakeRegistry()
    loop = AgentLoop(
        perception=BatchPerception(),
        planner=OneClickPerPlanThenSuccess(),
        registry=registry,
        events=EventBus(),
        safety=FakeSafety(),
        config=AgentConfig(batch_verify=False),
    )
    result = loop.run(Task(instruction="click twice"))
    assert result.status == "SUCCESS"
    # one click per plan, both plans ran (one full observe each)
    assert registry.names.count("click") == 2, "both clicks still ran"


def test_loop_success_verifies_previous_inline():
    """plan=[click, success]: click is verified inline before success runs."""
    class ClickThenSuccess:
        def __init__(self):
            self.calls = 0

        def plan(self, task, obs, diff, tools, history=None, hints=None):
            self.calls += 1
            if self.calls == 1:
                return Plan(actions=[Action("a-1", "click", {"x": 1}),
                                     Action("a-2", "success", {"result": "done"})])
            return Plan(actions=[Action("a-3", "success", {"result": "done"})])

    perception = ChangingPerception()
    loop = AgentLoop(
        perception=perception,
        planner=ClickThenSuccess(),
        registry=FakeRegistry(),
        events=EventBus(),
        safety=FakeSafety(),
        config=AgentConfig(),
    )
    result = loop.run(Task(instruction="click then done"))
    assert result.status == "SUCCESS"
    assert perception.light >= 1, "click must be inline-verified before success"


def test_loop_inline_verified_click_skips_pending_verify():
    """A click verified inline must NOT also set _pending_verify (no double check).

    Clicks target element_id=0 (a calculator digit with an ``expected``
    display change), so _capture_expected returns non-None and the batch-tail
    click WOULD defer to _pending_verify -- but the two inline-verified clicks
    must not. Only the batch-tail click runs _verify_pending once.
    """
    class SpyLoop(AgentLoop):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.pending_checks = 0

        def _verify_pending(self, obs):
            self.pending_checks += 1
            return super()._verify_pending(obs)

    class CalcPerception:
        """Calculator-like scene: display advances on every observe/light."""

        def __init__(self):
            self.count = 0

        def _next(self):
            els = [
                Element(0, "uia", text="7", role="button", bbox=(100, 300, 127, 48)),
                Element(1, "uia", text=str(self.count), role="text", bbox=(100, 10, 400, 80)),
            ]
            for i, e in enumerate(els):
                e.id = i
            sc = build_scene(els, active_window="Calculator")
            sc.display_ids = [1]
            self.count += 1
            return Observation(None, 1.0, "Calculator", 1.0, els, scene=sc)

        def observe(self):
            return self._next()

        def observe_light(self):
            return self._next()

    class ThreeClicksThenSuccess:
        def __init__(self):
            self.calls = 0

        def plan(self, task, obs, diff, tools, history=None, hints=None):
            self.calls += 1
            if self.calls == 1:
                return Plan(actions=[Action("a-1", "click", {"element_id": 0}),
                                     Action("a-2", "click", {"element_id": 0}),
                                     Action("a-3", "click", {"element_id": 0})])
            return Plan(actions=[Action("a-4", "success", {"result": "done"})])

    loop = SpyLoop(
        perception=CalcPerception(),
        planner=ThreeClicksThenSuccess(),
        registry=FakeRegistry(),
        events=EventBus(),
        safety=FakeSafety(),
        config=AgentConfig(),
    )
    result = loop.run(Task(instruction="click 7 thrice"))
    assert result.status == "SUCCESS"
    # clicks 1-2 were inline-verified (no pending), only the tail click (3)
    # deferred to _pending_verify -> exactly one _verify_pending call.
    assert loop.pending_checks == 1, loop.pending_checks
```

- [ ] **Step 6: 运行全部 loop 测试**

Run: `python -m pytest tests/integration/test_loop_mock.py tests/unit/test_batch.py -v`
Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add mio_cua/agent/loop.py tests/integration/test_loop_mock.py
git commit -m "feat: batch plan execution with per-step light verification"
```

---

### Task 5: Prompt 更新

**Files:**
- Modify: `mio_cua/prompts/system.txt:26`

- [ ] **Step 1: 修改**

将第 26 行：

```
- Do one meaningful action per step, then check the result and continue. Do not repeat the same action twice if it worked.
```

替换为：

```
- You may issue up to 3 closely-related actions in one plan when they are a tight sequence
  (e.g. typing a multi-digit number digit by digit). Each action is re-verified against the
  screen before the next runs. Do not repeat the same action twice if it worked.
```

- [ ] **Step 2: 确认无引用破坏**

Run: `python -m pytest tests/integration/test_planner.py tests/unit/test_scaffold.py -v`
Expected: PASS（prompt 未被测试断言为原文）。

- [ ] **Step 3: Commit**

```bash
git add mio_cua/prompts/system.txt
git commit -m "docs: allow up-to-3-action batches in system prompt"
```

---

### Task 6: 全量回归 + 收尾

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿。

- [ ] **Step 2: 冒烟冒烟脚本（可选，需真实桌面）**

Run: `python scripts/run_smoke_vdesk.py --only calculator --model <模型> --base-url <url>`
Expected: calculator 场景 PASS，验证批量点击 + display 验证仍工作。

- [ ] **Step 3: 更新 README 能力清单（如提及批量）**

确认 README「How it works」/ 特性列表是否需要补充「multi-step batch + live re-verification」一行；需要则修改并 commit。

- [ ] **Step 4: 提交收尾**

```bash
git add README.md
git commit -m "docs: mention multi-step batching with live verification"
```
