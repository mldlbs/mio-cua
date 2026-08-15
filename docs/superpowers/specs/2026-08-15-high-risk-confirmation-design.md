# 高风险动作确认机制 — 设计文档

> 日期：2026-08-15
> 状态：已批准（子项目 2 of 3）
> 所属：mio-cua v0.2 milestone

---

## 1. 背景与问题

mio-cua 允许 AI 操作真实桌面：移动文件、关窗口、杀进程。现有防护是「事后」的——
文件移动拒绝覆盖、F9 急停、step 限制。但**执行前没有用户确认**：一个 `kill_process`
或 `close_window` 会立即生效，用户来不及反悔。

**目标**：高风险动作（固定清单）执行前弹出桌面确认（确认/拒绝/超时拒绝）；用户拒绝时
action 返回失败且不重试，agent 换低风险方案或直接收尾。

## 2. 决策摘要（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 触发形态 | 弹窗确认（桌面通知 + 确认/拒绝按钮） |
| 高风险清单 | 固定清单（delete / overwrite / kill_process / close_window），不支持敏感词扩展 |
| 交互与超时 | 确认/拒绝两按钮；超时自动拒绝（默认 30s） |
| 拒绝后反馈 | action 返回失败 + `retryable=False`（不重试） |
| 架构位置 | ToolRegistry 包装层（CLI/MCP/SDK 自动生效） |

## 3. 架构与组件

### 3.1 高风险清单（新文件 `mio_cua/safety/risk.py`）

```python
"""High-risk tool registry: tools that need user confirmation before running."""

HIGH_RISK = {
    "delete": "Delete a file/folder (irreversible)",
    "overwrite": "Overwrite an existing file",
    "kill_process": "End a running process",
    "close_window": "Close a window (may lose unsaved work)",
}
```

判定：工具 schema 携带 `risk: "high"` 标记，`is_high_risk(name)` 检查该标记。
builtin registry 中高风险工具注册时 schema 带标记；MCP 工具带 `destructiveHint: True`
的映射到同一组。

**说明（YAGNI）**：
- 现有 builtin registry（`make_dir/move_file/move_files/list_dir`）**没有**真正的
  delete/kill 工具，`move_file` 已内置「拒绝覆盖」。故 builtin 侧暂无高风险工具需标记。
- 高风险清单主要为 **MCP 工具**（`mio_kill_process`、`mio_close_window`）和**未来新增
  delete 类工具**预留。MCP 侧现有 `destructiveHint=True` 的正好两个。
- 不在本子项目新增 delete 工具（避免范围膨胀；那是另一个功能）。

### 3.2 确认器（新文件 `mio_cua/safety/confirm.py`）

```python
"""User-confirmation gate for high-risk actions.

A blocking desktop dialog (confirm/deny) with a timeout that auto-denies.
Denial returns retryable=False so the agent never retries a rejected action.
"""

class Confirmation:
    def __init__(self, timeout_s: float = 30.0, enabled: bool = True):
        self.timeout_s = timeout_s
        self.enabled = enabled

    def confirm(self, tool_name: str, params: dict) -> bool:
        """Ask the user before a high-risk tool runs.

        Returns True (approved) / False (denied or timed out).
        When disabled (--headless / MIO_CUA_CONFIRM_OFF=1) returns True without
        prompting so automation keeps working.
        """
        if not self.enabled:
            return True
        return _ask(tool_name, self._describe(tool_name, params), self.timeout_s)
```

- **弹窗实现**：`ctypes.windll.user32.MessageBoxW(hwnd=0, text, title, MB_YESNO | MB_TOPMOST | MB_ICONWARNING)`。
  超时用后台线程计时，超时自动执行「拒绝」（关闭消息框并按 No）。
- **禁用开关**：环境变量 `MIO_CUA_CONFIRM_OFF=1` 或 `Confirmation(enabled=False)` →
  跳过弹窗直接放行（无人值守/自动化）。SDK 用户可显式传入自己的确认回调。
- **消息文案**：`f"mio-cua 想执行高风险操作:\n\n{tool_name}\n{describe}\n\n确认？"`

### 3.3 Registry 包装层（改 `mio_cua/tools/registry.py`）

```python
class ToolRegistry:
    def __init__(self, confirmation=None):
        self._confirmation = confirmation or Confirmation()

    def call(self, name: str, params: dict, ctx: ToolContext):
        if self._needs_confirmation(name) and not self._confirmation.confirm(name, params):
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
```

要点：
- 确认层只包住高风险工具；低风险路径零开销（一次 dict 查 + 字段比对）。
- `retryable=False` 关键：loop 的 recover 不会重试被拒动作，直接失败 → 整批中止
  （复用子项目 1 的 `_batch_failed`）。
- 测试友好：`ToolRegistry(confirmation=FakeConfirm(return_value=False))`。

### 3.4 builtin schema 增加 risk 字段（改 `mio_cua/tools/builtin.py`）

现有 builtin 工具均非高风险（`move_file` 已内置覆盖保护），**不修改**任何 schema。
仅当未来新增 delete 类工具时在 schema 加 `"risk": "high"`。`_SCHEMAS` 结构支持
`function` 内任意字段，无需改动注册逻辑。

### 3.5 MCP 集成（改 `mio_cua/mcp_server.py`）

`_run()` 包装器对高风险工具先确认。高风险判定基于工具名到 HIGH_RISK 的显式映射
（MCP 工具名与 HIGH_RISK 键不完全一致，故用别名表对齐 `destructiveHint: True` 的工具）：

```python
# 别名表：MCP 工具名 -> HIGH_RISK 语义键
_MCP_HIGH_RISK = {
    "mio_kill_process": "kill_process",
    "mio_close_window": "close_window",
}

def _run(func, *args, **kwargs):
    name = getattr(func, "__name__", "")
    key = _MCP_HIGH_RISK.get(name)
    if key is not None:
        if not CONFIRMATION.confirm(key, kwargs):
            return f"Rejected by user: {name}"
    res = func(_StubCtx(), *args, **kwargs)
    return res.message if res.success else f"Error: {res.message}"
```

`CONFIRMATION` 模块级单例，`MIO_CUA_CONFIRM_OFF=1` 时禁用。
新增高风险 MCP 工具时只需在 `_MCP_HIGH_RISK` 加一行；若漏加，§6.4 有覆盖性校验测试。
未来若新增 `mio_delete` 类工具，同样在此表登记。

## 4. 数据流

```
registry.call("kill_process", ...)
  └─ _needs_confirmation("kill_process")?  → 是
       └─ Confirmation.confirm(...)  → 弹窗（确认/拒绝/超时30s）
            ├─ 确认 → 执行工具 → 返回结果
            └─ 拒绝/超时 → ActionResult(success=False, retryable=False,
                                       "user rejected ...")
                       → loop: 不 recover，记录失败，整批中止（_batch_failed）
```

## 5. 错误处理与安全

- 超时 → 自动拒绝（安全优先，无人值守不静默执行高风险操作）。
- `MIO_CUA_CONFIRM_OFF=1` 或 `enabled=False` → 跳过弹窗放行（显式选择）。
- 弹窗失败（无桌面/权限）→ 记为拒绝（fail-closed）。
- 被拒动作不重试（`retryable=False`）；agent 从 history 看到拒绝原因可换方案或收尾。
- 与现有 `move_file` 覆盖保护正交：`move_file` 不标高风险，其内部「拒绝覆盖」逻辑不变。

## 6. 测试

### 6.1 单元（`tests/unit/test_confirm.py`）
- `Confirmation(enabled=False)` → confirm 返回 True，不弹窗。
- `Confirmation` 弹窗路径用 `_ask` 打桩：确认→True，拒绝→False。
- 超时：monkeypatch 计时器，超时自动拒绝。
- `_needs_confirmation`：schema 带 `risk:high` → True；无 → False。

### 6.2 Registry 包装（`tests/unit/test_registry.py`）
- 高风险工具被拒 → `ActionResult(success=False, retryable=False)`，底层 func 未调用。
- 高风险工具确认 → func 被调用。
- 低风险工具 → 直接调用，无确认路径。
- `FakeConfirm` 可注入。

### 6.3 集成（`tests/integration/test_loop_mock.py`）
- plan 含 high-risk action 被拒 → 失败，不 recover（history 无 recovered 标记），整批中止，
  `_batch_failed` 注入下轮 hint。
- plan 含 high-risk action 确认 → 正常执行。
- `MIO_CUA_CONFIRM_OFF=1` → 无确认直接执行。

### 6.4 MCP（`tests/unit/test_mcp_server.py`）
- `mio_kill_process` / `mio_close_window` 被拒 → 返回 "Rejected by user"。
- 确认 → 正常结果。
- `CONFIRMATION` 禁用 → 直接执行。

## 7. 不在范围内（YAGNI）

- 敏感词扩展（type/key 内容检测）——用户未选择。
- delete 工具本身（本子项目只加确认层）。
- 「仅本次允许」/「总是允许」白名单记忆。
- 每工具自定义确认文案模板（统一文案足够）。
- 确认历史审计（现有 artifact 截图已留痕）。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 弹窗阻塞无人值守运行 | `MIO_CUA_CONFIRM_OFF=1` / `enabled=False` 显式跳过 |
| 超时后自动拒绝导致任务失败 | 安全优先的刻意取舍；agent 可换低风险方案或收尾 |
| 误标高风险（低风险工具被弹窗打扰） | 固定清单最小化（仅 delete/overwrite/kill/close），其余不打扰 |
| 弹窗不可用（无桌面会话） | fail-closed 记为拒绝 |
| 未来新增 delete 工具忘记标 risk | schema 校验测试：新增工具若名字在 HIGH_RISK 必须带标记 |
