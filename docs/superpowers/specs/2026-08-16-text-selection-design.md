# 文本选择能力（drag / clipboard / select_element）— 设计文档

> 日期：2026-08-16
> 状态：已批准（子项目 5）
> 所属：mio-cua（实测驱动）

---

## 1. 背景与问题

实测任务"从 DeepSeek Chat 复制长回复并保存"暴露了核心缺口：**agent 无法选中网页上的
指定文本**。根因：
- `Ctrl+A` 全选会包含侧边栏 → 复制到错误内容
- 没有"框选指定区域"的工具
- 没有 `clipboard_get` 验证复制结果 → agent 不知道自己复制对了没
- OmniParser 缺失进一步削弱元素定位

**目标**：补齐文本选择能力链——框选/选中 → 复制 → **验证** → 保存。

## 2. 决策摘要（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 工具集 | drag + clipboard_get + clipboard_set + select_element 四个 |
| select_element 实现 | **基于 drag 拖拽**，不用 Shift+Click（跨应用行为分裂、依赖焦点） |
| 工具分层 | drag/clipboard 是基础工具（primitive）；select_element 是组合工具（composite，封装 drag） |
| 验证闭环 | select → Ctrl+C → clipboard_get 验证含预期文本 → 不对重选（clipboard_get 是闭环关键） |
| 优先级 | clipboard_get ★★★★★、drag ★★★★★、clipboard_set ★★★★、select_element ★★★ |
| 注册范围 | builtin + MCP 全部 |

## 3. 架构与组件

### 3.1 文件结构

```
mio_cua/tools/
├── fs.py          # 既有：list_dir/read_file/write_file/...
├── clipboard.py   # 新：clipboard_get / clipboard_set
├── drag.py        # 新：drag（从 mcp_server 提取）
└── selection.py   # 新：select_element（组合 drag）
```

依赖方向：`select_element → drag → mouse backend`。
**不复制 `mio_drag` 的实现**——drag 是 MCP 与 builtin 共享的单一实现。

### 3.2 基础工具（Primitive）

**`mio_cua/tools/drag.py`**

```python
def drag(ctx, x1=None, y1=None, x2=None, y2=None, element_id=None):
    """Press the left button at (x1,y1), drag to (x2,y2), release.

    For selecting text ranges, moving icons, drawing, etc. Optionally accepts
    an element_id (uses its bbox: from left-edge to right-edge at mid-height).
    Backend already implements smooth drag (20 steps).
    """
    # 解析：element_id → (x1,y1,x2,y2)（bbox 左缘+2 → 右缘-2，y=中）
    # 委托 ctx.controller.execute(Action(type="drag", params=...))
```

后端 `automation/backends.py` 已有 `typ == "drag"` 的平滑拖拽实现（20 步），直接复用。
`drag` 是纯坐标 primitive，不承诺文本选择语义。

**`mio_cua/tools/clipboard.py`**（从 mcp_server 提取逻辑）

```python
def clipboard_get(ctx):
    """Return the current clipboard text.

    Structured result: text / has_text / length. Distinguishes:
      - empty clipboard or no CF_UNICODETEXT  -> text="" (has_text=False)
      - OpenClipboard failure                 -> tool error (retryable=True)
    An empty read is NOT an error -- the caller decides whether to retry.
    """
    # win32clipboard.OpenClipboard → CF_UNICODETEXT → GetClipboardData
    # 返回 ActionResult(success=True, message=json.dumps({...}))

def clipboard_set(ctx, text=None):
    """Put text on the clipboard. Combine with ctrl+v to paste without typing."""
    # OpenClipboard → EmptyClipboard → SetClipboardText(CF_UNICODETEXT)
```

**clipboard_get 结构化结果**：

```json
{ "text": "some text", "has_text": true, "length": 9 }
```

- 正常空剪贴板 / 无 CF_UNICODETEXT → `text=""`、`has_text=false`（**不是错误**）
- `OpenClipboard` 失败 → ActionResult(success=False, retryable=True)（**错误**，区别于空）

### 3.3 组合工具（Composite）

**`mio_cua/tools/selection.py`**

```python
def select_element(ctx, element_id=None):
    """Select an element's text by dragging across its bbox (SINGLE-LINE text).

    Implemented as drag(left+2, mid_y) -> drag(right-2, mid_y). NOT Shift+Click
    (which depends on focus and behaves inconsistently across apps). The caller
    should copy (ctrl+c) and verify with clipboard_get.

    Assumes a SINGLE-LINE text element (mid-height horizontal drag). Multi-line
    text ranges are NOT supported in this version -- if field testing shows
    long multi-line blocks, add a separate text_range/multi-segment capability
    later instead of complicating this primitive.
    """
    if element_id is None:
        return ActionResult(... "element_id required", retryable=True)
    element = resolve element_id from ctx.current_observation
    left, top, width, height = element.bbox
    x1 = left + 2
    x2 = max(x1 + 1, left + width - 2)   # 保证 x1 < x2，width<=4 时最小跨度 1
    y = top + height // 2
    return drag(ctx, x1=x1, y1=y, x2=x2, y2=y)
```

**关键定位**：
- select_element 是 drag 的便捷封装（单行文本假设），不是"选中一定成功"的保证。
- 方向保证 `x1 < x2`（避免 RTL/异常布局导致反向拖拽）。
- 宽度保护 `x2 = max(x1+1, right-2)`（width<=4 的边界元素仍可拖）。
- 不自动复制、不自动验证——复制和验证是 Agent 层决策，**不新增 select_and_copy()**。

### 3.4 验证闭环（Agent 层行为，非工具行为）

```
select_element      # 操作（工具）
      ↓
key(ctrl+c)         # 操作（工具）
      ↓
clipboard_get       # 观测（工具）
      ↓
semantic check      # 决策（Agent：clipboard 是否含预期文本）
      ↓
匹配? ──是──> write_file() 保存
   │否
   ↓
retry selection     # 重新 drag / select_element
```

**职责分层**：
- `select_element` = 操作（选中尝试）
- `clipboard_get` = 观测（拿到复制结果）
- **Agent = 决策**（比对 clipboard 内容是否匹配，决定继续/重试）

**不新增 `select_and_copy()`** 之类组合——否则会逐渐堆积
`click_and_wait` / `find_and_click` / `copy_and_verify`，primitive/composite 边界失控。
验证逻辑沉淀为 Agent 的 prompt/hints 行为，而非新工具。

### 3.5 注册

- **builtin**（`mio_cua/tools/builtin.py`）：`drag` / `clipboard_get` / `clipboard_set` /
  `select_element` 四个注册 + schema。
- **MCP**（`mio_cua/mcp_server.py`）：已有 `mio_drag` / `mio_clipboard_get` /
  `mio_clipboard_set`，改为调用 `tools/drag.py` / `tools/clipboard.py`（消除重复实现）；
  新增 `mio_select_element`。
- 全部只读/低风险，不标 `risk:"high"`。

## 4. 数据流

```
Agent loop:
  select_element(id) → drag 底层 → 鼠标框选
  key(ctrl+c)        → 系统剪贴板
  clipboard_get()    → 文本 → 校验
  write_file()       → 保存到磁盘
```

MCP 与 builtin 共享 `tools/drag.py` / `tools/clipboard.py` 单一实现。

## 5. 错误处理与安全

- `clipboard_get`：剪贴板无文本 → 返回空串（不是错误），agent 据空结果重选。
- `select_element`：element_id 无 → retryable=True；bbox 异常（宽<4）→ 失败。
- `clipboard_set`：text 缺失 → 失败 retryable=True。
- 无高风险：select/drag/clipboard 均为用户可见操作，不触发确认弹窗。

## 6. 测试

### 6.1 单元（`tests/unit/test_clipboard.py`、`test_drag.py`、`test_selection.py`）

- `clipboard_get/set`：设置后读取 round-trip；空剪贴板 → `text=""` / `has_text=false`
  （**不是错误**，success=True）；`OpenClipboard` 失败 → success=False, retryable=True。
- `drag`：mock controller，验证 Action 参数透传（x1/y1/x2/y2）；element_id 解析到 bbox。
- `select_element`：mock observation 含元素，验证内部调用 drag 的 bbox 内缩参数
  （left+2 → max(left+1, left+width-2)，y 中）；**width<=4 的边界元素** → 仍能拖
  （x1<x2 保证）；element_id 缺失 → 失败。
- `select_element` 单行假设：不宣称多行选择（无多行测试，第一版不做）。

### 6.2 MCP（`tests/unit/test_mcp_server.py`）

- `mio_select_element` 新工具存在。
- `mio_drag` / `mio_clipboard_get` / `mio_clipboard_set` 仍工作（提取后无回归）。

### 6.3 集成（`tests/integration/test_loop_mock.py`）

- loop 中 select_element → clipboard_get 验证链路（fake registry 记录动作顺序）。
- 验证闭环由 Agent 决策：测试断言 clipboard_get 返回结构化结果可被 agent 判读。

## 7. 不在范围内（YAGNI）

- 不改 OmniParser（模型权重下载，非代码问题）。
- select_element 不自动复制、不自动验证（Agent 层决策；不新增 select_and_copy()）。
- 不用 Shift+Click 实现选择（drag 是通用语义）。
- **多行文本选择**（第一版单行假设；实测发现需要再加 text_range/多段选择）。
- 不做"选中后直接返回文本"（侵入性强，破坏工具单一职责）。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| drag 选中范围不准（含相邻文本） | 验证闭环兜底：clipboard_get 校验，不对重选 |
| 多行元素中线横拖只选中一行 | 第一版明确单行假设；实测后加 text_range 多段选择 |
| bbox 内缩不够 / width<=4 边界 | x2=max(x1+1, right-2) 保证可拖；失败靠重试 |
| 空剪贴板被误判为"没选中" | clipboard_get 结构化返回（text/has_text/length），空≠错误 |
| OpenClipboard 失败被吞成空串 | 区分：失败 → success=False retryable=True；空 → success=True |
| 反向拖拽（RTL/异常布局） | select_element 保证 x1<x2 |
| 提取后 MCP 行为回归 | 单元测试覆盖 mio_drag/clipboard 仍工作 |
