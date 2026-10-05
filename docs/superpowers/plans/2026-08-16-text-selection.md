# 文本选择能力（drag / clipboard / select_element）— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐"选中正确内容"能力链：`clipboard_get/set`、`drag`（primitive）+ `select_element`（composite，封装 drag），配合 Agent 层验证闭环（select → Ctrl+C → clipboard_get 校验 → 重选）。

**Architecture:** 新增 `mio_cua/tools/clipboard.py`（结构化返回）、`mio_cua/tools/drag.py`（从 mcp_server 提取统一实现）、`mio_cua/tools/selection.py`（select_element = drag 的 bbox 内缩封装，单行文本假设）。builtin 注册 4 个工具；MCP 现有 `mio_drag`/`mio_clipboard_*` 改为调用新模块（消除重复），补 `mio_select_element`。

**Tech Stack:** Python 3.10+，win32clipboard，pytest。

**Spec:** `docs/superpowers/specs/2026-08-16-text-selection-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `mio_cua/tools/clipboard.py` | clipboard_get（结构化）/ clipboard_set | **Create** |
| `mio_cua/tools/drag.py` | drag（primitive，element_id 解析 + 委托 backend） | **Create** |
| `mio_cua/tools/selection.py` | select_element（composite，封装 drag） | **Create** |
| `mio_cua/tools/builtin.py` | 注册 4 个工具 + schema | Modify |
| `mio_cua/mcp_server.py` | mio_drag/clipboard 改为调用新模块；补 mio_select_element | Modify |
| `tests/unit/test_clipboard.py` | clipboard 单测 | **Create** |
| `tests/unit/test_drag.py` | drag 单测 | **Create** |
| `tests/unit/test_selection.py` | select_element 单测 | **Create** |
| `tests/unit/test_mcp_server.py` | MCP 新工具 + 提取后无回归 | Modify |
| `README.md` | MCP 工具数 + 能力描述 | Modify |

---

### Task 1: `mio_cua/tools/clipboard.py`

**Files:**
- Create: `mio_cua/tools/clipboard.py`
- Test: `tests/unit/test_clipboard.py`（Create）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_clipboard.py`：

```python
import json

from mio_cua.tools.clipboard import clipboard_get, clipboard_set
from mio_cua.models.action_result import ActionResult


class Ctx:
    current_action_id = "t"


def _read_clipboard():
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return ""
    finally:
        win32clipboard.CloseClipboard()


def test_set_then_get_roundtrip():
    r = clipboard_set(Ctx(), text="hello 世界")
    assert r.success is True
    r2 = clipboard_get(Ctx())
    assert r2.success is True
    data = json.loads(r2.message)
    assert data["text"] == "hello 世界"
    assert data["has_text"] is True
    assert data["length"] == len("hello 世界")


def test_get_empty_clipboard_is_success():
    # clear clipboard first
    clipboard_set(Ctx(), text="")
    r = clipboard_get(Ctx())
    assert r.success is True
    data = json.loads(r.message)
    assert data["text"] == ""
    assert data["has_text"] is False
    assert data["length"] == 0


def test_set_requires_text():
    r = clipboard_set(Ctx())
    assert r.success is False
    assert r.retryable is True


def test_get_returns_structured_json():
    clipboard_set(Ctx(), text="abc")
    r = clipboard_get(Ctx())
    data = json.loads(r.message)
    assert set(data.keys()) == {"text", "has_text", "length"}
    assert data == {"text": "abc", "has_text": True, "length": 3}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_clipboard.py -v`
Expected: FAIL（ModuleNotFoundError: mio_cua.tools.clipboard）。

- [ ] **Step 3: 实现**

创建 `mio_cua/tools/clipboard.py`：

```python
"""Clipboard tools: read/write the Windows clipboard text.

``clipboard_get`` returns a STRUCTURED result (text / has_text / length) so the
agent can distinguish "empty clipboard" (not an error) from a clipboard access
failure (error, retryable). The agent verifies a copy by reading back the
clipboard and checking the content matches expectations.
"""

import json

from mio_cua.models.action_result import ActionResult


def clipboard_get(ctx):
    """Return the current clipboard text as a structured result.

    Result JSON: {"text": ..., "has_text": bool, "length": int}.
    Empty clipboard / no CF_UNICODETEXT -> text="" has_text=False (SUCCESS, not
    an error). OpenClipboard failure -> success=False, retryable=True.
    """
    import win32clipboard
    try:
        win32clipboard.OpenClipboard()
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, f"clipboard unavailable: {e}", retryable=True)
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        else:
            text = ""
    finally:
        win32clipboard.CloseClipboard()
    data = {"text": text, "has_text": bool(text), "length": len(text)}
    return ActionResult(ctx.current_action_id, True, json.dumps(data, ensure_ascii=False))


def clipboard_set(ctx, text=None):
    """Put ``text`` on the clipboard. Combine with a ctrl+v to paste without
    typing (fast + reliable for long content)."""
    if text is None:
        return ActionResult(ctx.current_action_id, False, "text required", retryable=True)
    import win32clipboard
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(str(text), win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return ActionResult(ctx.current_action_id, True, "clipboard set")
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_clipboard.py -v`
Expected: PASS（5 个）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/clipboard.py tests/unit/test_clipboard.py
git commit -m "feat: add clipboard_get/set tools with structured result"
```

---

### Task 2: `mio_cua/tools/drag.py`

**Files:**
- Create: `mio_cua/tools/drag.py`
- Test: `tests/unit/test_drag.py`（Create）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_drag.py`：

```python
from mio_cua.tools.drag import drag
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult
from mio_cua.models.element import Element
from mio_cua.models.observation import Observation


class Ctx:
    current_action_id = "t"


class RecordingController:
    def __init__(self):
        self.calls = []
        self.current_observation = None

    def execute(self, action):
        self.calls.append(action)
        return RawResult(sent=True)


def test_drag_passes_coordinates():
    ctrl = RecordingController()
    ctx = Ctx()
    ctx.controller = ctrl
    r = drag(ctx, x1=10, y1=20, x2=100, y2=200)
    assert r.success is True
    a = ctrl.calls[-1]
    assert a.type == "drag"
    assert a.params["x1"] == 10
    assert a.params["y1"] == 20
    assert a.params["x2"] == 100
    assert a.params["y2"] == 200


def test_drag_requires_coordinates():
    ctrl = RecordingController()
    ctx = Ctx()
    ctx.controller = ctrl
    r = drag(ctx)
    assert r.success is False
    assert r.retryable is True


def test_drag_resolves_element_id():
    ctrl = RecordingController()
    ctrl.current_observation = Observation(
        None, 1.0, "win", 1.0,
        [Element(0, "uia", text="x", role="text", bbox=(100, 200, 300, 40))],
    )
    ctx = Ctx()
    ctx.controller = ctrl
    r = drag(ctx, element_id=0)
    a = ctrl.calls[-1]
    assert a.type == "drag"
    assert a.params["x1"] == 102  # left + 2
    assert a.params["y1"] == 220  # top + height//2
    assert a.params["x2"] == 398  # left + width - 2
    assert a.params["y2"] == 220
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_drag.py -v`
Expected: FAIL（ModuleNotFoundError: mio_cua.tools.drag）。

- [ ] **Step 3: 实现**

创建 `mio_cua/tools/drag.py`：

```python
"""Drag tool: press and drag the mouse between two points (primitive).

Text selection, icon moving and sliders all start from a drag. This is a pure
coordinate primitive -- higher-level tools (e.g. select_element) build on it.
"""

from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


def drag(ctx, x1=None, y1=None, x2=None, y2=None, element_id=None):
    """Press the left button at (x1,y1), drag to (x2,y2), release.

    Optionally resolves ``element_id`` to its bbox (from left+2 to right-2 at
    mid-height) when no explicit coordinates are given.
    """
    if element_id is not None:
        x1, y1, x2, y2 = _resolve_element(ctx, element_id)
    if x1 is None or y1 is None or x2 is None or y2 is None:
        return ActionResult(ctx.current_action_id, False,
                            "x1/y1/x2/y2 or element_id required", retryable=True)
    result = ctx.controller.execute(Action(
        id=ctx.current_action_id, type="drag",
        params={"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)},
    ))
    return ActionResult(ctx.current_action_id, result.sent,
                        result.error or "dragged", retryable=not result.sent)


def _resolve_element(ctx, element_id):
    # observations live on the CONTROLLER (loop sets controller.current_observation);
    # fall back to ctx.current_observation which ToolContext also carries.
    obs = getattr(ctx.controller, "current_observation", None) or ctx.current_observation
    if obs is None:
        raise RuntimeError("element_id unresolved: no observation available")
    for e in obs.elements:
        if e.id == element_id or str(e.id) == str(element_id):
            left, top, width, height = e.bbox
            x1 = left + 2
            x2 = max(x1 + 1, left + width - 2)
            y = top + height // 2
            return x1, y, x2, y
    raise RuntimeError(f"element_id {element_id!r} not found in current observation")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_drag.py -v`
Expected: PASS（3 个）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/drag.py tests/unit/test_drag.py
git commit -m "feat: add drag primitive tool"
```

---

### Task 3: `mio_cua/tools/selection.py`（select_element）

**Files:**
- Create: `mio_cua/tools/selection.py`
- Test: `tests/unit/test_selection.py`（Create）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_selection.py`：

```python
from mio_cua.tools.selection import select_element
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult
from mio_cua.models.element import Element
from mio_cua.models.observation import Observation


class Ctx:
    current_action_id = "t"


class RecordingController:
    def __init__(self):
        self.calls = []
        self.current_observation = None

    def execute(self, action):
        self.calls.append(action)
        return RawResult(sent=True)


def _obs(bbox):
    return Observation(None, 1.0, "win", 1.0,
                       [Element(0, "uia", text="txt", role="text", bbox=bbox)])


def test_select_element_drags_across_bbox():
    ctrl = RecordingController()
    ctrl.current_observation = _obs((100, 200, 300, 40))
    ctx = Ctx()
    ctx.controller = ctrl
    r = select_element(ctx, element_id=0)
    assert r.success is True
    a = ctrl.calls[-1]
    assert a.type == "drag"
    assert a.params["x1"] == 102   # left + 2
    assert a.params["y1"] == 220   # top + height//2
    assert a.params["x2"] == 398   # left + width - 2
    assert a.params["y2"] == 220


def test_select_element_handles_tiny_width():
    # width=2 -> x2 must be at least x1+1 (x1 < x2 guaranteed)
    ctrl = RecordingController()
    ctrl.current_observation = _obs((100, 200, 2, 40))
    ctx = Ctx()
    ctx.controller = ctrl
    r = select_element(ctx, element_id=0)
    assert r.success is True
    a = ctrl.calls[-1]
    assert a.params["x1"] < a.params["x2"]
    assert a.params["x1"] == 102
    assert a.params["x2"] == 103


def test_select_element_requires_element_id():
    ctrl = RecordingController()
    ctx = Ctx()
    ctx.controller = ctrl
    r = select_element(ctx)
    assert r.success is False
    assert r.retryable is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_selection.py -v`
Expected: FAIL（ModuleNotFoundError: mio_cua.tools.selection）。

- [ ] **Step 3: 实现**

创建 `mio_cua/tools/selection.py`：

```python
"""Text selection: select an element's text by dragging across its bbox.

``select_element`` is a COMPOSITE tool built on ``drag`` (not Shift+Click, which
depends on focus and behaves inconsistently across apps). It assumes SINGLE-LINE
text (mid-height horizontal drag). The agent copies with ctrl+c and verifies the
result via ``clipboard_get``; verification is the Agent's decision, not this
tool's.
"""

from mio_cua.models.action_result import ActionResult
from mio_cua.tools.drag import drag


def select_element(ctx, element_id=None):
    """Select an element's text by dragging from its left edge to its right edge
    at mid-height (SINGLE-LINE text assumption). Caller copies with ctrl+c and
    verifies via clipboard_get."""
    if element_id is None:
        return ActionResult(ctx.current_action_id, False,
                            "element_id required", retryable=True)
    obs = getattr(ctx.controller, "current_observation", None) or ctx.current_observation
    if obs is None:
        return ActionResult(ctx.current_action_id, False,
                            "no observation available to resolve element_id", retryable=True)
    for e in obs.elements:
        if e.id == element_id or str(e.id) == str(element_id):
            left, top, width, height = e.bbox
            x1 = left + 2
            x2 = max(x1 + 1, left + width - 2)
            y = top + height // 2
            return drag(ctx, x1=x1, y1=y, x2=x2, y2=y)
    return ActionResult(ctx.current_action_id, False,
                        f"element_id {element_id!r} not found in current observation",
                        retryable=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_selection.py -v`
Expected: PASS（3 个）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/selection.py tests/unit/test_selection.py
git commit -m "feat: add select_element composite tool (drag-based)"
```

---

### Task 4: builtin 注册 + MCP 重构

**Files:**
- Modify: `mio_cua/tools/builtin.py`
- Modify: `mio_cua/mcp_server.py`
- Test: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_registry.py` 末尾追加：

```python
def test_builtin_registers_selection_tools():
    from mio_cua.tools.builtin import register_builtin_tools
    reg = ToolRegistry(confirmation=Confirmation(enabled=False))
    register_builtin_tools(reg)
    names = set(reg.names())
    for t in ("drag", "clipboard_get", "clipboard_set", "select_element"):
        assert t in names, f"{t} not registered"
```

在 `tests/unit/test_mcp_server.py` 末尾追加：

```python
def test_mcp_select_element_tool_exists():
    from mio_cua.mcp_server import mcp
    names = {t.name for t in _run(mcp.list_tools())}
    assert "mio_select_element" in names


def test_mcp_clipboard_set_get_roundtrip():
    from mio_cua.mcp_server import mcp
    _run(mcp.call_tool("mio_clipboard_set", {"text": "roundtrip-test"}))
    content, _ = _run(mcp.call_tool("mio_clipboard_get", {}))
    assert "roundtrip-test" in content[0].text


def test_mcp_drag_requires_coords():
    from mio_cua.mcp_server import mcp
    # mcp 1.27+ raises ToolError for missing required Field arg (protocol-level
    # error, same message a client sees) rather than returning error content.
    import pytest
    with pytest.raises(Exception) as exc:
        _run(mcp.call_tool("mio_drag", {}))
    assert "required" in str(exc.value) or "Field required" in str(exc.value)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_registry.py::test_builtin_registers_selection_tools tests/unit/test_mcp_server.py::test_mcp_select_element_tool_exists -v`
Expected: FAIL（drag/clipboard 未注册；mio_select_element 不存在）。

- [ ] **Step 3: 实现**

**3a. `mio_cua/tools/builtin.py`**：

1. import 行追加 `from mio_cua.tools import drag as drag_tool, clipboard as clipboard_tool, selection as selection_tool`（或局部 import）。
2. `_SCHEMAS` 追加 4 个 schema：

```python
    "drag": {"type": "function", "function": {"name": "drag", "description": "Press and drag the mouse from (x1,y1) to (x2,y2), then release. For selecting text ranges or moving items.", "parameters": {"type": "object", "properties": {
        "x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"},
        "element_id": {"type": "integer"}}}}},
    "select_element": {"type": "function", "function": {"name": "select_element", "description": "Select an element's text by dragging across its bbox (single-line). Then ctrl+c and verify with clipboard_get.", "parameters": {"type": "object", "properties": {
        "element_id": {"type": "integer"}}, "required": ["element_id"]}}},
    "clipboard_get": {"type": "function", "function": {"name": "clipboard_get", "description": "Read the clipboard text as structured JSON {text,has_text,length}. Use AFTER ctrl+c to verify what was copied.", "parameters": {"type": "object", "properties": {}}}},
    "clipboard_set": {"type": "function", "function": {"name": "clipboard_set", "description": "Put text on the clipboard (combine with ctrl+v to paste without typing).", "parameters": {"type": "object", "properties": {
        "text": {"type": "string"}}, "required": ["text"]}}},
```

3. `register_builtin_tools` for 列表追加：

```python
        ("drag", drag_tool.drag),
        ("select_element", selection_tool.select_element),
        ("clipboard_get", clipboard_tool.clipboard_get),
        ("clipboard_set", clipboard_tool.clipboard_set),
```

**3b. `mio_cua/mcp_server.py`**：

1. 现有 `mio_drag` 函数体改为调用新模块：

```python
async def mio_drag(x1: int = Field(..., description="Start X"), y1: int = Field(..., description="Start Y"),
                   x2: int = Field(..., description="End X"), y2: int = Field(..., description="End Y")) -> str:
    """Press left button at (x1,y1), drag to (x2,y2), release. For moving
    window/file icons, selecting ranges, or sliders."""
    from mio_cua.tools.drag import drag
    from mio_cua.automation.input_controller import InputController
    ctrl = InputController()
    r = ctrl.execute(Action(id="mcp", type="drag",
                            params={"x1": x1, "y1": y1, "x2": x2, "y2": y2}))
    return "dragged" if r.sent else f"Error: {r.error}"
```

2. 现有 `mio_clipboard_get` / `mio_clipboard_set` 函数体改为调用新模块（结构化结果原样返回 message）：

```python
async def mio_clipboard_get() -> str:
    """Return the current clipboard text as structured JSON {text,has_text,length}."""
    from mio_cua.tools.clipboard import clipboard_get
    return _run(clipboard_get)
```

```python
async def mio_clipboard_set(text: str = Field(..., description="Text to place on the clipboard")) -> str:
    """Put text on the clipboard. Combine with a ctrl+v to paste without typing."""
    from mio_cua.tools.clipboard import clipboard_set
    return _run(clipboard_set, text=text)
```

3. 新增 `mio_select_element`（先 observe 建立上下文，再调用 select_element，保证 element_id 可解析）：

```python
@mcp.tool(name="mio_select_element", annotations={
    "title": "Select an element's text", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_select_element(element_id: int = Field(..., description="Element id to select (from mio_observe_scene)")) -> str:
    """Select an element's text by dragging across its bbox (single-line text).
    Caller then presses ctrl+c and verifies with mio_clipboard_get."""
    from mio_cua.tools.selection import select_element
    from mio_cua.automation.input_controller import InputController
    from mio_cua.perception import Perception
    ctrl = InputController()
    ctrl.current_observation = Perception().observe()
    ctx = _StubCtx()
    ctx.controller = ctrl
    ctx.current_observation = ctrl.current_observation
    res = select_element(ctx, element_id=element_id)
    return res.message if res.success else f"Error: {res.message}"
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_registry.py tests/unit/test_mcp_server.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/builtin.py mio_cua/mcp_server.py tests/unit/test_registry.py tests/unit/test_mcp_server.py
git commit -m "feat: register selection tools and refactor MCP to shared modules"
```

---

### Task 5: 全量回归 + README + 实测

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（预期 ~290 个）。

- [ ] **Step 2: README 更新**

`README.md`：工具数 31 → 35；MCP 工具清单补 `select_element` / `drag` / `clipboard_get` / `clipboard_set`。

`MCP.md`：工具表格补 4 行。

Commit：`git add README.md MCP.md && git commit -m "docs: mention text selection tools in MCP list"`

- [ ] **Step 3: 实测（可选，需真实桌面）**

重跑"DeepSeek 回复复制保存"任务，验证：`select_element` 选中回复 → `key(ctrl+c)` → `clipboard_get` 验证 → `write_file` 保存。
