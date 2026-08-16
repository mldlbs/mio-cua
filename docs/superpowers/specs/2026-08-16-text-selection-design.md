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

**`mio_cua/tools/clipboard.py`**（从 mcp_server 提取逻辑）

```python
def clipboard_get(ctx):
    """Return the current clipboard text ('' if none)."""
    # win32clipboard.OpenClipboard → CF_UNICODETEXT → GetClipboardData

def clipboard_set(ctx, text=None):
    """Put text on the clipboard. Combine with ctrl+v to paste without typing."""
    # OpenClipboard → EmptyClipboard → SetClipboardText(CF_UNICODETEXT)
```

### 3.3 组合工具（Composite）

**`mio_cua/tools/selection.py`**

```python
def select_element(ctx, element_id=None):
    """Select an element's text by dragging across its bbox.

    Implemented as drag(left+2, mid_y) -> drag(right-2, mid_y). NOT Shift+Click
    (which depends on focus and behaves inconsistently across apps). The caller
    should copy (ctrl+c) and verify with clipboard_get.
    """
    if element_id is None:
        return ActionResult(... "element_id required", retryable=True)
    element = resolve element_id from ctx.current_observation
    left, top, width, height = element.bbox
    return drag(ctx, x1=left + 2, y1=top + height // 2,
                x2=left + width - 2, y2=top + height // 2)
```

**关键定位**：select_element 只是 drag 的便捷封装（避免 agent 手算 bbox 内缩）。它不是
"选中一定成功"的保证——真正的保障是**验证闭环**。

### 3.4 验证闭环（核心）

```
select_element(id)          # 尝试选中
        ↓
key(ctrl+c)                 # 复制
        ↓
clipboard_get()             # 读取剪贴板
        ↓
含预期文本？ ──是──> write_file() 保存
        │否
        ↓
重新 drag / select_element  # 重选
```

- **clipboard_get 是闭环的关键**：没有它，agent 无法判断复制是否成功，也无法确认选中
  的是否是正确内容（比如全选复制到了侧边栏）。
- select_element 语义是"尝试选择"，不承诺选中正确文本；验证负责最终确认。

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

- `clipboard_get/set`：设置后读取 round-trip；空剪贴板 → 空串。
- `drag`：mock controller，验证 Action 参数透传（x1/y1/x2/y2）。
- `select_element`：mock observation 含元素，验证内部调用 drag 的 bbox 内缩参数
  （left+2 → left+width-2，y 中）；element_id 缺失 → 失败。

### 6.2 MCP（`tests/unit/test_mcp_server.py`）

- `mio_select_element` 新工具存在。
- `mio_drag` / `mio_clipboard_get` / `mio_clipboard_set` 仍工作（提取后无回归）。

### 6.3 集成（`tests/integration/test_loop_mock.py`）

- loop 中 select_element → clipboard_get 验证链路（fake registry 记录动作顺序）。

## 7. 不在范围内（YAGNI）

- 不改 OmniParser（模型权重下载，非代码问题）。
- select_element 不自动复制（保持单步职责，agent 自己 Ctrl+C）。
- 不用 Shift+Click 实现选择（drag 是通用语义）。
- 不做"选中后直接返回文本"（侵入性强，破坏工具单一职责）。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| drag 选中范围不准（含相邻文本） | 验证闭环兜底：clipboard_get 校验，不对重选 |
| bbox 内缩不够（贴边选中失败） | left+2 / right-2 留边距；失败靠重试 |
| 剪贴板被其他程序占用 | OpenClipboard 失败 → 失败重试 |
| 提取后 MCP 行为回归 | 单元测试覆盖 mio_drag/clipboard 仍工作 |
