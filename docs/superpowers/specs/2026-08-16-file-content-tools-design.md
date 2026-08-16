# 文件内容工具（read / write / search）— 设计文档

> 日期：2026-08-16
> 状态：已批准（子项目 4）
> 所属：mio-cua v0.2 milestone 后续

---

## 1. 背景与问题

当前文件系统工具只有 `list_dir` / `make_dir` / `move_file` / `move_files`（`mio_cua/tools/fs.py`）。
**没有读取文件内容、写入文件、搜索文件的工具**。这卡住了跨应用场景的核心链路：
"读文件数据 → 加工（如计算器求和）→ 保存结果"——agent 只能靠开记事本/看屏幕去读，
既慢又脆弱。

**目标**：新增 `read_file` / `write_file` / `search_files` 三个确定性工具，补齐
"读→算→写"链路。CLI/SDK/MCP 全通道可用。

## 2. 决策摘要（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 工具集 | read_file + write_file + search_files 三件套 |
| 写入安全 | `mode`（create/append/write）+ 覆盖已有文件需显式 `allow_overwrite=True` |
| 代码组织 | 扩展现有 `mio_cua/tools/fs.py`（不新建模块） |
| 返回值 | read_file 前 N 字符（默认 2000，可配 max_chars，超长附截断提示）；search_files 结果上限 50 条 |
| 外部 SDK | **不引入** Claude Code / Codex 等 SDK 作为运行时依赖；仅借鉴其 API 语义（Read/Write/Glob/Grep），实现完全自研（几十行） |

### 2.1 架构决策：抄 API，不抄实现

参考 Claude Code / Codex 的 Read/Write/Glob/Grep 语义划分，但**不依赖任何外部 SDK**：

- `read_file` ← Read 语义（读文本、可截断）
- `write_file` ← Write 语义（写入、覆盖需显式允许）
- `search_files` ← Glob（按名/扩展）+ Grep（按内容）合并

理由：
1. **场景不同**：Claude Code 是代码代理（工作空间 = 仓库）；mio-cua 是计算机使用代理
   （工作空间 = 整个 Windows 桌面）。工具集不同源。
2. **接口统一**：mio-cua 已有 `ToolRegistry → ActionResult → CLI/SDK/MCP` 单一抽象；
   引入外部 SDK 会引入 `Claude ToolResult` / `Codex FileOperationResult` 等多套结果类型，
   需写适配器。
3. **安全模型不同**：mio-cua 用显式参数控制（`mode` + `allow_overwrite`）；
   Claude Code 用 Diff 预览/确认流。绑定 SDK = 绑定其安全策略。
4. **不被抽象绑架**：自研 `search_files` 的 `name/ext/pattern` 可自由演进为
   `regex/exclude` 等，不受 SDK 版本限制。
5. **SDK 不稳定**：Claude Code / Codex 均快速迭代（Read/Write/Edit →
   ReadFile/WriteFile/PatchFile）。核心能力不应绑定外部项目版本节奏。

**实现成本极低**：read_file ≈20 行、write_file ≈30 行、search_files ≈50 行，
总计 <100 行自研代码。为了省这点代码引入外部 SDK，不划算。

## 3. 架构与组件

### 3.1 `mio_cua/tools/fs.py` 新增三个工具

```python
def read_file(ctx, path=None, max_chars=2000):
    """Read a text file, returning the first ``max_chars`` characters.

    Truncated files report how many chars were cut. Binary/unreadable files
    fail with retryable=True (the caller may OCR the screen instead).
    """

def write_file(ctx, path=None, content=None, mode="create", allow_overwrite=False):
    """Write ``content`` to ``path``.

    mode:
      create  -> only creates a NEW file; refuses if it already exists
      append  -> appends to an existing file (creates if missing)
      write   -> overwrites an existing file, but ONLY if ``allow_overwrite``
    Parent directories are created as needed.
    """

def search_files(ctx, path=None, name=None, ext=None, pattern=None, max_results=50):
    """Recursively search ``path`` for files.

    Filters (all optional, combined with AND):
      name    -> filename must CONTAIN this substring (case-insensitive)
      ext     -> extension must equal this (no dot, e.g. 'txt')
      pattern -> file CONTENT must contain this string (text files only)
    Returns up to ``max_results`` matching paths (default 50).
    """
```

**细节：**

- `read_file`：
  - 缺 path → 失败（retryable=True）
  - 文件不存在 → 失败（retryable=True）
  - 读取前 `max_chars`；若总长 > max_chars，结果追加
    `\n...(truncated, {total} chars total)`；否则正常返回
  - `max_chars` 上限 100_000（防爆上下文，超限 clamp 到 100_000）
  - 二进制/解码错误 → 失败（retryable=True，提示"可能不是文本文件"）

- `write_file`：
  - 缺 path 或 content → 失败（retryable=True）
  - `mode` 校验：非法 mode → 失败（retryable=True）
  - `create`：文件已存在 → 失败（`retryable=False`，消息含"refusing to overwrite"）
  - `write`：文件已存在且 `allow_overwrite` 为 False → 失败（`retryable=False`，
    消息含"refusing to overwrite"）；`allow_overwrite=True` → 覆盖
  - `append`：追加；文件不存在则创建
  - 自动 `os.makedirs(parent, exist_ok=True)`，再写文件
  - 编码 UTF-8

- `search_files`：
  - 缺 path → 失败（retryable=True）
  - `os.walk(path)` 递归；跳过目录、只统计文件
  - `name` 匹配：`filename.lower()` 含 `name.lower()`
  - `ext` 匹配：`splitext(filename)[1].lstrip(".")` == `ext.lower()`
  - `pattern` 匹配：读取文件文本（`errors="ignore"` 容错二进制）含 `pattern`
  - 收集命中路径（绝对路径，`os.path.join`），按 `max_results` 截断
  - 命中超上限 → 消息附 `...and N more`
  - 一个文件读取出错（权限/二进制）→ 跳过继续，不中断

### 3.2 `mio_cua/tools/builtin.py` 注册

`_SCHEMAS` 新增 3 个 schema + `register_builtin_tools` 列表新增 3 项：

```python
"read_file": {name read_file, desc, params: {path: string(required), max_chars: integer(optional, default 2000)}}
"write_file": {name write_file, desc, params: {path: string(required), content: string(required),
               mode: string enum[create,append,write] default create, allow_overwrite: boolean default false}}
"search_files": {name search_files, desc, params: {path: string(required), name: string(optional),
               ext: string(optional), pattern: string(optional), max_results: integer(optional, default 50)}}
```

### 3.3 `mio_cua/mcp_server.py` 三个薄包装

```python
@mcp.tool(name="mio_read_file", annotations={readOnlyHint: True, destructiveHint: False, ...})
async def mio_read_file(path, max_chars=2000):
    return _run(read_file, path=path, max_chars=max_chars)

@mcp.tool(name="mio_write_file", annotations={readOnlyHint: False, destructiveHint: True, ...})
async def mio_write_file(path, content, mode="create", allow_overwrite=False):
    return _run(write_file, path=path, content=content, mode=mode, allow_overwrite=allow_overwrite)

@mcp.tool(name="mio_search_files", annotations={readOnlyHint: True, destructiveHint: False, ...})
async def mio_search_files(path, name=None, ext=None, pattern=None, max_results=50):
    return _run(search_files, path=path, name=name, ext=ext, pattern=pattern, max_results=max_results)
```

**安全说明**：`mio_write_file` 的 annotation 标 `destructiveHint: True`（通知 MCP 客户端
这是破坏性工具），但**不登记进 `_MCP_HIGH_RISK`**——因为覆盖保护由显式
`allow_overwrite` 参数承担（用户已选择"mode + 显式允许"，而非确认弹窗）。
`read_file` / `search_files` 纯只读，无风险。

### 3.4 与确认机制正交

`write_file` 不触发 SP2 的确认弹窗。覆盖已有文件的行为由参数显式控制：
- `create` 模式从不覆盖
- `write` 模式覆盖需 `allow_overwrite=True`
- `append` 从不破坏已有内容

## 4. 数据流

```
read_file(path, max_chars=2000)
  └─ 读取前 N 字符 ──> 文本 / truncated 提示 / 失败

write_file(path, content, mode="create", allow_overwrite=False)
  └─ create: 已存在? → 拒绝 │ append: 追加 │ write: allow_overwrite? → 覆盖/拒绝
  └─ makedirs(parent) ──> 写入 UTF-8

search_files(path, name?, ext?, pattern?, max_results=50)
  └─ os.walk ──> 过滤(name/ext/pattern) ──> 前 max_results 条
```

## 5. 错误处理与安全

- read/search 只读，无副作用。
- write 的覆盖保护是**参数级**（`allow_overwrite`），非弹窗——符合用户选择。
- `max_chars` clamp 到 100_000，防超长文件爆 LLM 上下文。
- `search_files` 单文件读取失败跳过，不中断整个搜索。
- 所有工具沿用现有 `ActionResult` 约定（`retryable` 区分可重试错误 vs 拒绝）。

## 6. 测试

### 6.1 单元（`tests/unit/test_fs.py` 扩展）

- `read_file`：正常读取 / 截断（内容含 truncated 提示）/ 文件缺失失败 / 二进制乱码失败 / max_chars clamp
- `write_file`：create 新建成功 / create 已存在拒绝（retryable=False）/ append 追加 / append 不存在则创建 / write 需 allow_overwrite（默认拒绝）/ write allow_overwrite=True 覆盖成功 / 父目录自动创建 / 非法 mode 失败
- `search_files`：按 name / 按 ext / 按 pattern / 组合过滤 / max_results 截断 / 缺失 path 失败

### 6.2 MCP（`tests/unit/test_mcp_server.py` 扩展）

- `mio_read_file` / `mio_write_file` / `mio_search_files` 经 `mcp.call_tool` 在 tmp_path 上真实调用

### 6.3 集成（`tests/integration/test_loop_mock.py` 或 CLI）

- loop 中 `read_file` 被调用（fake registry 记录）→ 正常执行
- （可选）CLI `run "读文件..." --simulate-scenario` 用 stub provider

## 7. 不在范围内（YAGNI）

- 二进制文件读写（仅文本 UTF-8）
- delete 工具（SP2 已明确不做）
- write 走确认弹窗（用户选参数级保护）
- 路径通配符/glob 搜索（固定 name/ext/pattern 语义足够）
- **不引入** Claude Code / Codex / OpenHands 等外部 SDK 作为运行时依赖（见 §2.1）

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 读超大文件爆上下文 | max_chars 默认 2000 + clamp 100_000 + 截断提示 |
| 覆盖重要文件 | create 永不覆盖；write 需显式 allow_overwrite；append 不破坏已有内容 |
| 搜索大目录慢/卡 | 仅命中才读内容（name/ext 先过滤）；pattern 搜索逐文件 errors="ignore"；上限 50 |
| 二进制文件被当文本 | read 解码错误→失败提示；search pattern 用 errors="ignore" 跳过 |
