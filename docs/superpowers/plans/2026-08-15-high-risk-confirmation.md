# 高风险动作确认机制 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 高风险工具（delete/overwrite/kill_process/close_window）执行前弹桌面确认（确认/拒绝/超时拒绝）；拒绝时 action 返回失败且不重试。

**Architecture:** 新增 `mio_cua/safety/` 包承载风险清单（`risk.py`）与确认器（`confirm.py`，弹窗 + 超时 fail-closed，`MIO_CUA_CONFIRM_OFF=1` 可禁用）。`ToolRegistry` 构造时注入 `Confirmation`，`call()` 对 schema 带 `risk:"high"` 的工具先确认、拒绝返回 `retryable=False`。MCP 侧 `_run()` 用别名表拦截 `mio_kill_process`/`mio_close_window`。

**Tech Stack:** Python 3.10+，ctypes MessageBoxW，pytest，现有 `ActionResult`/`ToolRegistry`/`AgentLoop`。

**Spec:** `docs/superpowers/specs/2026-08-15-high-risk-confirmation-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `mio_cua/safety/__init__.py` | 包标记 | **Create** |
| `mio_cua/safety/risk.py` | `HIGH_RISK` 清单 + `is_high_risk()` | **Create** |
| `mio_cua/safety/confirm.py` | `Confirmation` + `_ask` 弹窗（超时自动拒绝） | **Create** |
| `mio_cua/tools/registry.py` | `call()` 高风险确认包装 | Modify |
| `mio_cua/mcp_server.py` | `_run()` 拦截高风险 MCP 工具 | Modify |
| `tests/unit/test_risk.py` | 风险清单 | **Create** |
| `tests/unit/test_confirm.py` | 确认器全分支 | **Create** |
| `tests/unit/test_registry.py` | 包装层行为 | Modify |
| `tests/integration/test_loop_mock.py` | loop 集成（拒绝/确认/禁用） | Modify |

---

### Task 1: 风险清单 `mio_cua/safety/risk.py`

**Files:**
- Create: `mio_cua/safety/__init__.py`
- Create: `mio_cua/safety/risk.py`
- Test: `tests/unit/test_risk.py`（Create）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_risk.py`：

```python
from mio_cua.safety.risk import HIGH_RISK, is_high_risk


def test_high_risk_contains_expected_tools():
    assert "delete" in HIGH_RISK
    assert "overwrite" in HIGH_RISK
    assert "kill_process" in HIGH_RISK
    assert "close_window" in HIGH_RISK


def test_is_high_risk():
    assert is_high_risk("kill_process") is True
    assert is_high_risk("close_window") is True
    assert is_high_risk("click") is False
    assert is_high_risk("type") is False
    assert is_high_risk("") is False
    assert is_high_risk(None) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_risk.py -v`
Expected: FAIL（ModuleNotFoundError: mio_cua.safety.risk）。

- [ ] **Step 3: 实现**

创建 `mio_cua/safety/__init__.py`（空文件，包标记）。

创建 `mio_cua/safety/risk.py`：

```python
"""High-risk tool registry: tools that need user confirmation before running."""

HIGH_RISK = {
    "delete": "Delete a file/folder (irreversible)",
    "overwrite": "Overwrite an existing file",
    "kill_process": "End a running process",
    "close_window": "Close a window (may lose unsaved work)",
}


def is_high_risk(tool_name) -> bool:
    """True if the tool needs user confirmation before running."""
    return bool(tool_name) and tool_name in HIGH_RISK
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_risk.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/safety/__init__.py mio_cua/safety/risk.py tests/unit/test_risk.py
git commit -m "feat: add high-risk tool registry"
```

---

### Task 2: 确认器 `mio_cua/safety/confirm.py`

**Files:**
- Create: `mio_cua/safety/confirm.py`
- Test: `tests/unit/test_confirm.py`（Create）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_confirm.py`：

```python
import threading
import time

import pytest

from mio_cua.safety.confirm import Confirmation, _ask


def test_disabled_confirmation_passes_through():
    c = Confirmation(enabled=False)
    assert c.confirm("kill_process", {"name": "notepad.exe"}) is True


def test_env_off_disables(monkeypatch):
    monkeypatch.setenv("MIO_CUA_CONFIRM_OFF", "1")
    c = Confirmation()  # enabled resolved from env
    assert c.enabled is False
    assert c.confirm("kill_process", {}) is True


def test_env_unset_enables(monkeypatch):
    monkeypatch.delenv("MIO_CUA_CONFIRM_OFF", raising=False)
    c = Confirmation()
    assert c.enabled is True


def test_ask_yes_returns_true():
    def fake_dialog(text, title):
        return 6  # IDYES

    assert _ask("t", "text", 5.0, dialog=fake_dialog) is True


def test_ask_no_returns_false():
    def fake_dialog(text, title):
        return 7  # IDNO

    assert _ask("t", "text", 5.0, dialog=fake_dialog) is False


def test_ask_dialog_error_fails_closed():
    def boom(text, title):
        raise RuntimeError("no desktop session")

    assert _ask("t", "text", 5.0, dialog=boom) is False


def test_ask_timeout_denies():
    def slow(text, title):
        time.sleep(5)

    start = time.time()
    assert _ask("t", "text", 0.05, dialog=slow) is False
    assert time.time() - start < 2.0, "timeout must not wait for the dialog"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_confirm.py -v`
Expected: FAIL（ModuleNotFoundError: mio_cua.safety.confirm）。

- [ ] **Step 3: 实现**

创建 `mio_cua/safety/confirm.py`：

```python
"""User-confirmation gate for high-risk actions.

A blocking desktop Yes/No dialog with a timeout that auto-denies (fail-closed).
Denial returns ``retryable=False`` upstream so the agent never retries a
rejected action. Set ``MIO_CUA_CONFIRM_OFF=1`` (or ``enabled=False``) to skip
the prompt entirely for headless/automation runs.
"""

import os
import threading

from mio_cua.safety.risk import HIGH_RISK

_DIALOG_TITLE = "mio-cua — 高风险操作确认"

MB_YESNO = 0x04
MB_ICONWARNING = 0x30
MB_DEFBUTTON2 = 0x100
MB_TOPMOST = 0x40000
IDYES = 6
WM_CLOSE = 0x0010


def _message_box(text, title):
    """Show a blocking Yes/No dialog; returns the Win32 result code."""
    import ctypes
    return ctypes.windll.user32.MessageBoxW(
        None, text, title, MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_TOPMOST,
    )


def _ask(title, text, timeout_s, dialog=_message_box) -> bool:
    """Show a confirm/deny dialog with a timeout that auto-denies.

    Any outcome other than an explicit YES (No, Esc, WM_CLOSE from the
    timeout, or a dialog error) is treated as a denial -- fail-closed.
    """
    result = {}

    def _show():
        try:
            result["value"] = dialog(text, title)
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_show, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        _close_dialog(title)
        t.join(1.0)
        return False
    if "error" in result:
        return False
    return result.get("value") == IDYES


def _close_dialog(title):
    """Post WM_CLOSE to the dialog so the blocked thread can exit."""
    import ctypes
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    except Exception:
        pass


class Confirmation:
    def __init__(self, timeout_s: float = 30.0, enabled: bool = None):
        self.timeout_s = timeout_s
        if enabled is None:
            enabled = os.environ.get("MIO_CUA_CONFIRM_OFF", "1") != "1"
        self.enabled = enabled

    def confirm(self, tool_name: str, params=None) -> bool:
        """Ask the user before a high-risk tool runs.

        Returns True (approved) or False (denied / timed out / disabled path
        returns True without prompting).
        """
        if not self.enabled:
            return True
        return _ask(_DIALOG_TITLE, self._describe(tool_name, params), self.timeout_s)

    @staticmethod
    def _describe(tool_name, params) -> str:
        why = HIGH_RISK.get(tool_name, tool_name)
        p = ", ".join(f"{k}={v!r}" for k, v in (params or {}).items())
        return (f"mio-cua 想执行高风险操作:\n\n{tool_name}\n{why}\n"
                f"参数: {p or '(无)'}\n\n确认执行？")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_confirm.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/safety/confirm.py tests/unit/test_confirm.py
git commit -m "feat: add Confirmation gate with timeout fail-closed"
```

---

### Task 3: Registry 包装层

**Files:**
- Modify: `mio_cua/tools/registry.py`
- Test: `tests/unit/test_registry.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_registry.py` 顶部追加导入：

```python
from mio_cua.safety.confirm import Confirmation
```

追加测试：

```python
class FakeConfirm:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def confirm(self, name, params):
        self.calls.append((name, params))
        return self.answer


def _tool(ctx, value=None):
    return ActionResult(action_id="a-1", success=True, message="ran")


def test_high_risk_denied_returns_failure_no_retry():
    confirm = FakeConfirm(False)
    reg = ToolRegistry(confirmation=confirm)
    reg.register("delete", _tool, {"type": "function", "function": {
        "name": "delete", "risk": "high"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("delete", {"target": "x.txt"}, ctx)
    assert result.success is False
    assert result.retryable is False
    assert "user rejected" in result.message
    assert confirm.calls == [("delete", {"target": "x.txt"})]


def test_high_risk_approved_runs_tool():
    confirm = FakeConfirm(True)
    reg = ToolRegistry(confirmation=confirm)
    reg.register("delete", _tool, {"type": "function", "function": {
        "name": "delete", "risk": "high"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("delete", {"target": "x.txt"}, ctx)
    assert result.success is True
    assert result.message == "ran"
    assert confirm.calls == [("delete", {"target": "x.txt"})]


def test_low_risk_skips_confirmation():
    confirm = FakeConfirm(False)  # would deny, but must never be asked
    reg = ToolRegistry(confirmation=confirm)
    reg.register("click", _tool, {"type": "function", "function": {"name": "click"}})
    ctx = ToolContext(controller=None, perception=None, config=None, events=None)
    result = reg.call("click", {"x": 1}, ctx)
    assert result.success is True
    assert confirm.calls == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_registry.py -v`
Expected: 新增 3 个测试 FAIL（`ToolRegistry.__init__` 不接受 `confirmation` 参数）。

- [ ] **Step 3: 实现**

修改 `mio_cua/tools/registry.py`：

```python
from typing import Callable, Dict, Tuple

from mio_cua.models.action_result import ActionResult
from mio_cua.safety.confirm import Confirmation
from mio_cua.tools.context import ToolContext


class ToolRegistry:
    def __init__(self, confirmation: Confirmation = None):
        self._confirmation = confirmation or Confirmation()
        self._tools: Dict[str, Tuple[Callable, dict]] = {}

    def register(self, name: str, func: Callable, schema: dict):
        self._tools[name] = (func, schema)

    def call(self, name: str, params: dict, ctx: ToolContext):
        if self._needs_confirmation(name):
            if not self._confirmation.confirm(name, params):
                return ActionResult(
                    ctx.current_action_id, False,
                    f"user rejected {name}: {params}", retryable=False,
                )
        func, _ = self._tools[name]
        return func(ctx, **params)

    def _needs_confirmation(self, name: str) -> bool:
        _, schema = self._tools.get(name, (None, None))
        fn = (schema or {}).get("function", {})
        return fn.get("risk") == "high"

    def schemas(self) -> list:
        return [schema for _, schema in self._tools.values()]

    def names(self) -> list:
        return list(self._tools.keys())
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_registry.py -v`
Expected: 全部 PASS（含既有 3 个）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/registry.py tests/unit/test_registry.py
git commit -m "feat: confirm high-risk tools in ToolRegistry"
```

---

### Task 4: MCP 拦截

**Files:**
- Modify: `mio_cua/mcp_server.py:46-59`
- Test: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_mcp_server.py` 顶部追加导入：

```python
from mio_cua.models.action_result import ActionResult
```

追加测试：

```python
class _FakeMCPConfirm:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def confirm(self, name, params):
        self.calls.append((name, params))
        return self.answer


def test_mcp_high_risk_rejected_before_running(monkeypatch):
    from mio_cua import mcp_server

    monkeypatch.setattr(mcp_server, "CONFIRMATION", _FakeMCPConfirm(False))
    ran = []

    def kill(ctx, **kw):
        ran.append(kw)
        return ActionResult("x", True, "killed")

    kill.__name__ = "mio_kill_process"
    out = mcp_server._run(kill, pid=1)
    assert out == "Rejected by user: mio_kill_process"
    assert ran == [], "the tool must NOT run when rejected"


def test_mcp_high_risk_approved_runs(monkeypatch):
    from mio_cua import mcp_server

    monkeypatch.setattr(mcp_server, "CONFIRMATION", _FakeMCPConfirm(True))

    def kill(ctx, **kw):
        return ActionResult("x", True, "killed")

    kill.__name__ = "mio_kill_process"
    out = mcp_server._run(kill, pid=1)
    assert out == "killed"


def test_mcp_low_risk_skips_confirmation(monkeypatch):
    from mio_cua import mcp_server

    fake = _FakeMCPConfirm(False)  # would deny, but must never be asked
    monkeypatch.setattr(mcp_server, "CONFIRMATION", fake)

    def focus(ctx, **kw):
        return ActionResult("x", True, "focused")

    focus.__name__ = "mio_focus_window"
    out = mcp_server._run(focus, title="Calc")
    assert out == "focused"
    assert fake.calls == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_mcp_server.py::test_mcp_high_risk_rejected_before_running -v`
Expected: FAIL（`mcp_server.CONFIRMATION` 不存在，AttributeError）。

- [ ] **Step 3: 实现**

修改 `mio_cua/mcp_server.py`：

1. 顶部（`_prewarm_omniparser` 之后）新增模块级确认器与别名表：

```python
from mio_cua.safety.confirm import Confirmation

CONFIRMATION = Confirmation()

# MCP tool name -> HIGH_RISK semantic key. New high-risk tools MUST be added
# here (and mirror destructiveHint: True on the @mcp.tool annotation).
_MCP_HIGH_RISK = {
    "mio_kill_process": "kill_process",
    "mio_close_window": "close_window",
}
```

2. 将现有 `_run`：

```python
def _run(func, *args, **kwargs):
    """Call a mio-cua tool and return its ActionResult message."""
    res = func(_StubCtx(), *args, **kwargs)
    if res.success:
        return res.message
    return f"Error: {res.message}"
```

替换为：

```python
def _run(func, *args, **kwargs):
    """Call a mio-cua tool and return its ActionResult message.

    High-risk tools (see _MCP_HIGH_RISK) are confirmed first; a denial returns
    a rejection message and the tool never runs.
    """
    name = getattr(func, "__name__", "")
    key = _MCP_HIGH_RISK.get(name)
    if key is not None:
        if not CONFIRMATION.confirm(key, kwargs):
            return f"Rejected by user: {name}"
    res = func(_StubCtx(), *args, **kwargs)
    if res.success:
        return res.message
    return f"Error: {res.message}"
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_mcp_server.py -v`
Expected: 全部 PASS（含既有 11 个）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat: confirm high-risk MCP tools before running"
```

---

### Task 5: Loop 集成测试

**Files:**
- Test: `tests/integration/test_loop_mock.py`

无需改 loop.py —— 拒绝路径天然走现有 `if not result.success: self._batch_failed = ...; break`（子项目 1 已实现）。只加测试验证。

- [ ] **Step 1: 写失败测试**

在 `tests/integration/test_loop_mock.py` 末尾追加：

```python
def test_loop_high_risk_denied_aborts_batch_no_retry():
    """A high-risk action the user rejects returns retryable=False; the loop
    must not recover it, must abort the batch, and must surface a GUIDANCE
    hint on the replan."""
    from mio_cua.safety.confirm import Confirmation
    from mio_cua.tools.context import ToolContext
    from mio_cua.tools.registry import ToolRegistry

    class FakeConfirm:
        def confirm(self, name, params):
            return False

    ran = []

    def delete(ctx, target=None):
        ran.append(target)
        return ActionResult(ctx.current_action_id, True, "deleted")

    registry = ToolRegistry(confirmation=FakeConfirm())
    registry.register("delete", delete, {"type": "function", "function": {
        "name": "delete", "risk": "high"}})
    # also register the tools the loop may reach (click after delete, success/fail)
    registry.register("click", _ok_tool, {"type": "function", "function": {"name": "click"}})
    registry.register("success", _ok_tool, {"type": "function", "function": {"name": "success"}})
    registry.register("fail", _ok_tool, {"type": "function", "function": {"name": "fail"}})

    hints_seen = []

    class DeleteThenSuccess:
        def __init__(self):
            self.calls = 0

        def plan(self, task, obs, diff, tools, history=None, hints=None):
            hints_seen.append(hints or [])
            self.calls += 1
            if self.calls == 1:
                return Plan(actions=[Action("a-1", "delete", {"target": "x.txt"}),
                                     Action("a-2", "click", {"x": 1})])
            return Plan(actions=[Action("a-3", "success", {"result": "done"})])

    loop = AgentLoop(
        perception=ChangingPerception(),
        planner=DeleteThenSuccess(),
        registry=registry,
        events=EventBus(),
        safety=FakeSafety(),
        config=AgentConfig(),
        history=None,
    )
    result = loop.run(Task(instruction="delete x.txt"))
    assert result.status == "SUCCESS"
    assert ran == [], "the rejected delete must never run"
    assert any("aborted because" in (h or "") for h in hints_seen[1]), \
        "GUIDANCE hint must reach the replan"
```

其中 `_ok_tool` 为模块级辅助（追加在文件顶部其它辅助函数旁）：

```python
def _ok_tool(ctx, **kwargs):
    return ActionResult(ctx.current_action_id, True, "ok")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/integration/test_loop_mock.py::test_loop_high_risk_denied_aborts_batch_no_retry -v`
Expected: FAIL（`registry.call` 未确认 → delete 直接执行 → `ran == ["x.txt"]`，断言 `ran == []` 失败）。

- [ ] **Step 3: 实现确认**

该测试无需改产品代码 —— Task 3 的 registry 包装已生效。运行确认即可。

Run: `python -m pytest tests/integration/test_loop_mock.py -v`
Expected: 全部 PASS（含新增 1 个）。

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_loop_mock.py
git commit -m "test: high-risk denial aborts batch without retry"
```

---

### Task 6: 全量回归 + 收尾

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（预期 ~219 个）。

- [ ] **Step 2: 确认既有 fs/其它测试未受影响**

重点确认 `tests/unit/test_fs.py`、`tests/unit/test_core_tools.py` 仍 PASS（`move_file` 不标高风险，行为不变）。

- [ ] **Step 3: 更新 README 安全章节**

`README.md` 的 🔒 Safety 列表加一行：

```
- High-risk actions (delete / kill / close) ask for **on-screen confirmation** before running (`MIO_CUA_CONFIRM_OFF=1` to disable)
```

Commit：`git add README.md && git commit -m "docs: mention high-risk action confirmation in safety"`

- [ ] **Step 4: 更新 spec/plan 勾选状态（可选）**

确认 spec 中 §6 测试均已落地，无遗留。
