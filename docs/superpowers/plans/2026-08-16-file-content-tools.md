# 文件内容工具（read / write / search）— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `read_file` / `write_file` / `search_files` 三个确定性文件内容工具（自研实现，零外部 SDK），补齐"读→算→写"跨应用链路，CLI/SDK/MCP 全通道可用。

**Architecture:** 在现有 `mio_cua/tools/fs.py` 追加三个函数（沿用 ActionResult/retryable 约定）；`builtin.py` 注册 + schema；`mcp_server.py` 加三个薄包装（`mio_read_file`/`mio_write_file`/`mio_search_files`）。write 的覆盖保护用显式 `allow_overwrite` 参数（参数级，非确认弹窗）。借鉴 Claude Code Read/Write/Glob/Grep 语义，但不依赖任何外部 SDK。

**Tech Stack:** Python 3.10+，标准库 os/shutil，pytest。

**Spec:** `docs/superpowers/specs/2026-08-16-file-content-tools-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `mio_cua/tools/fs.py` | 新增 read_file / write_file / search_files | Modify |
| `mio_cua/tools/builtin.py` | 注册 3 个工具 + schema | Modify |
| `mio_cua/mcp_server.py` | 3 个 MCP 薄包装 | Modify |
| `tests/unit/test_fs.py` | 三个工具的单测 | Modify |
| `tests/unit/test_mcp_server.py` | 3 个 MCP 工具测试 | Modify |
| `tests/unit/test_registry.py` | builtin 注册验证（可选） | Modify |
| `README.md` | MCP 工具清单 + 能力描述 | Modify |

---

### Task 1: `read_file`（fs.py + 单测）

**Files:**
- Modify: `mio_cua/tools/fs.py`
- Test: `tests/unit/test_fs.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_fs.py` 顶部 import 行改为：

```python
from mio_cua.tools.fs import make_dir, move_file, move_files, list_dir, read_file
```

在文件末尾追加：

```python
# --- read_file ---

def test_read_file_returns_content(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello world", encoding="utf8")
    r = read_file(Ctx(), path=str(p))
    assert r.success is True
    assert r.message == "hello world"


def test_read_file_truncates_with_notice(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * 5000, encoding="utf8")
    r = read_file(Ctx(), path=str(p), max_chars=100)
    assert r.success is True
    assert r.message.startswith("x" * 100)
    assert "truncated" in r.message
    assert "5000" in r.message


def test_read_file_missing_fails(tmp_path):
    r = read_file(Ctx(), path=str(tmp_path / "nope.txt"))
    assert r.success is False
    assert r.retryable is True


def test_read_file_requires_path():
    r = read_file(Ctx())
    assert r.success is False
    assert r.retryable is True


def test_read_file_binary_fails(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\x00\x01\x02\xff\xfe")
    r = read_file(Ctx(), path=str(p))
    assert r.success is False
    assert r.retryable is True


def test_read_file_clamps_max_chars(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hi", encoding="utf8")
    r = read_file(Ctx(), path=str(p), max_chars=999999)
    assert r.success is True
    assert r.message == "hi"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_fs.py -v`
Expected: 新增 6 个测试 FAIL（`read_file` 未定义，ImportError/NameError）。

- [ ] **Step 3: 实现**

在 `mio_cua/tools/fs.py` 末尾追加：

```python
_MAX_READ_CHARS = 100_000


def read_file(ctx, path=None, max_chars=2000):
    """Read a text file, returning the first ``max_chars`` characters.

    Truncated files report how many chars were cut. Binary/unreadable files
    fail with retryable=True (the caller may OCR the screen instead).
    """
    if not path:
        return ActionResult(ctx.current_action_id, False, "path required", retryable=True)
    if not os.path.isfile(path):
        return ActionResult(ctx.current_action_id, False, f"file not found: {path}", retryable=True)
    try:
        limit = min(int(max_chars or 2000), _MAX_READ_CHARS)
        with open(path, "r", encoding="utf8") as f:
            text = f.read()
    except UnicodeDecodeError:
        return ActionResult(ctx.current_action_id, False,
                            f"not a readable text file: {path}", retryable=True)
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
    if len(text) > limit:
        return ActionResult(ctx.current_action_id, True,
                            text[:limit] + f"\n...(truncated, {len(text)} chars total)")
    return ActionResult(ctx.current_action_id, True, text)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_fs.py -v`
Expected: 全部 PASS（既有 9 + 新 6 = 15）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/fs.py tests/unit/test_fs.py
git commit -m "feat: add read_file tool"
```

---

### Task 2: `write_file`（fs.py + 单测）

**Files:**
- Modify: `mio_cua/tools/fs.py`
- Test: `tests/unit/test_fs.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_fs.py` 末尾追加 `write_file` 测试前，先把顶部 import 行改为：

```python
from mio_cua.tools.fs import make_dir, move_file, move_files, list_dir, read_file, write_file
```

然后追加：

```python
# --- write_file ---

def test_write_file_create_new(tmp_path):
    p = tmp_path / "new.txt"
    r = write_file(Ctx(), path=str(p), content="hello")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "hello"


def test_write_file_create_refuses_existing(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("keep", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="new")
    assert r.success is False
    assert r.retryable is False
    assert "refusing" in r.message.lower()
    assert p.read_text(encoding="utf8") == "keep"


def test_write_file_append(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("one\n", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="two", mode="append")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "one\ntwo"


def test_write_file_append_creates_missing(tmp_path):
    p = tmp_path / "new.txt"
    r = write_file(Ctx(), path=str(p), content="x", mode="append")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "x"


def test_write_file_write_needs_allow_overwrite(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("keep", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="new", mode="write")
    assert r.success is False
    assert r.retryable is False
    assert "refusing" in r.message.lower()
    assert p.read_text(encoding="utf8") == "keep"


def test_write_file_write_with_allow_overwrite(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("keep", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="new", mode="write", allow_overwrite=True)
    assert r.success is True
    assert p.read_text(encoding="utf8") == "new"


def test_write_file_creates_parent_dirs(tmp_path):
    p = tmp_path / "x" / "y" / "a.txt"
    r = write_file(Ctx(), path=str(p), content="hi")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "hi"


def test_write_file_invalid_mode(tmp_path):
    p = tmp_path / "a.txt"
    r = write_file(Ctx(), path=str(p), content="x", mode="bogus")
    assert r.success is False
    assert r.retryable is True


def test_write_file_requires_args():
    r = write_file(Ctx(), path="x")
    assert r.success is False
    assert r.retryable is True
    r2 = write_file(Ctx(), content="x")
    assert r2.success is False
    assert r2.retryable is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_fs.py -v`
Expected: 新增 9 个测试 FAIL（`write_file` 未定义）。

- [ ] **Step 3: 实现**

在 `mio_cua/tools/fs.py` 末尾追加：

```python
_WRITE_MODES = ("create", "append", "write")


def write_file(ctx, path=None, content=None, mode="create", allow_overwrite=False):
    """Write ``content`` to ``path``.

    mode:
      create  -> only creates a NEW file; refuses if it already exists
      append  -> appends to an existing file (creates if missing)
      write   -> overwrites an existing file, but ONLY if ``allow_overwrite``
    Parent directories are created as needed.
    """
    if not path or content is None:
        return ActionResult(ctx.current_action_id, False, "path and content required", retryable=True)
    if mode not in _WRITE_MODES:
        return ActionResult(ctx.current_action_id, False,
                            f"invalid mode: {mode} (create/append/write)", retryable=True)
    try:
        if os.path.exists(path) and mode == "create":
            return ActionResult(ctx.current_action_id, False,
                                f"refusing to overwrite: {path}", retryable=False)
        if os.path.exists(path) and mode == "write" and not allow_overwrite:
            return ActionResult(ctx.current_action_id, False,
                                f"refusing to overwrite: {path} (set allow_overwrite=True)", retryable=False)
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        if mode == "append":
            with open(path, "a", encoding="utf8") as f:
                f.write(str(content))
            return ActionResult(ctx.current_action_id, True, f"appended to {path}")
        with open(path, "w", encoding="utf8") as f:
            f.write(str(content))
        return ActionResult(ctx.current_action_id, True, f"wrote {path}")
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_fs.py -v`
Expected: 全部 PASS（15 + 9 = 24）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/fs.py tests/unit/test_fs.py
git commit -m "feat: add write_file tool"
```

---

### Task 3: `search_files`（fs.py + 单测）

**Files:**
- Modify: `mio_cua/tools/fs.py`
- Test: `tests/unit/test_fs.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_fs.py` 末尾追加 `search_files` 测试前，先把顶部 import 行改为：

```python
from mio_cua.tools.fs import make_dir, move_file, move_files, list_dir, read_file, write_file, search_files
```

然后追加：

```python
# --- search_files ---

def test_search_by_name(tmp_path):
    (tmp_path / "report_2026.txt").write_text("x", encoding="utf8")
    (tmp_path / "other.md").write_text("y", encoding="utf8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "report_backup.txt").write_text("z", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), name="report")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("report_2026.txt" in ln for ln in lines)
    assert any("report_backup.txt" in ln for ln in lines)
    assert not any("other.md" in ln for ln in lines)


def test_search_by_ext(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf8")
    (tmp_path / "b.md").write_text("y", encoding="utf8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.TXT").write_text("z", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), ext="txt")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("a.txt" in ln for ln in lines)
    assert any("c.TXT" in ln for ln in lines)
    assert not any("b.md" in ln for ln in lines)


def test_search_by_content_pattern(tmp_path):
    (tmp_path / "a.txt").write_text("contains the magic word", encoding="utf8")
    (tmp_path / "b.txt").write_text("nothing special", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), pattern="magic")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("a.txt" in ln for ln in lines)
    assert not any("b.txt" in ln for ln in lines)


def test_search_combined_filters(tmp_path):
    (tmp_path / "notes_2026.txt").write_text("project alpha", encoding="utf8")
    (tmp_path / "notes_2026.md").write_text("project alpha", encoding="utf8")
    (tmp_path / "other.txt").write_text("project alpha", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), name="notes", ext="txt", pattern="alpha")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("notes_2026.txt" in ln for ln in lines)
    assert not any("notes_2026.md" in ln for ln in lines)
    assert not any("other.txt" in ln for ln in lines)


def test_search_respects_max_results(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), max_results=3)
    assert r.success is True
    lines = r.message.splitlines()
    assert len(lines) == 4  # 3 matches + "... and 7 more"
    assert "7 more" in r.message


def test_search_requires_path():
    r = search_files(Ctx())
    assert r.success is False
    assert r.retryable is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_fs.py -v`
Expected: 新增 6 个测试 FAIL（`search_files` 未定义）。

- [ ] **Step 3: 实现**

在 `mio_cua/tools/fs.py` 末尾追加：

```python
def search_files(ctx, path=None, name=None, ext=None, pattern=None, max_results=50):
    """Recursively search ``path`` for files.

    Filters (all optional, combined with AND):
      name    -> filename must CONTAIN this substring (case-insensitive)
      ext     -> extension must equal this (no dot, e.g. 'txt')
      pattern -> file CONTENT must contain this string (text files only)
    Returns up to ``max_results`` matching paths (default 50).
    """
    if not path:
        return ActionResult(ctx.current_action_id, False, "path required", retryable=True)
    if not os.path.isdir(path):
        return ActionResult(ctx.current_action_id, False, f"not a directory: {path}", retryable=True)
    try:
        limit = max(int(max_results or 50), 1)
        name_l = (name or "").lower()
        ext_l = (ext or "").lower().lstrip(".")
        hits = []
        for root, _dirs, files in os.walk(path):
            for fname in files:
                if name_l and name_l not in fname.lower():
                    continue
                if ext_l:
                    _, f_ext = os.path.splitext(fname)
                    if f_ext.lstrip(".").lower() != ext_l:
                        continue
                if pattern is not None:
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf8", errors="ignore") as f:
                            if pattern not in f.read():
                                continue
                    except OSError:
                        continue
                hits.append(os.path.join(root, fname))
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
        total = len(hits)
        shown = hits[:limit]
        msg = "\n".join(shown)
        if total > limit:
            msg += f"\n...and {total - limit} more"
        return ActionResult(ctx.current_action_id, bool(hits), msg, retryable=False)
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_fs.py -v`
Expected: 全部 PASS（24 + 6 = 30）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/fs.py tests/unit/test_fs.py
git commit -m "feat: add search_files tool"
```

---

### Task 4: builtin 注册

**Files:**
- Modify: `mio_cua/tools/builtin.py`
- Test: `tests/unit/test_registry.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_registry.py` 末尾追加：

```python
def test_builtin_registers_file_content_tools():
    from mio_cua.tools.builtin import register_builtin_tools
    reg = ToolRegistry(confirmation=Confirmation(enabled=False))
    register_builtin_tools(reg)
    names = set(reg.names())
    assert "read_file" in names
    assert "write_file" in names
    assert "search_files" in names
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_registry.py::test_builtin_registers_file_content_tools -v`
Expected: FAIL（`read_file` 不在注册表中）。

- [ ] **Step 3: 实现**

修改 `mio_cua/tools/builtin.py`：

1. `_SCHEMAS` 字典末尾（`list_dir` 之后）追加 3 个 schema：

```python
    "read_file": {"type": "function", "function": {"name": "read_file", "description": "Read a text file's first N characters (default 2000). Use to retrieve file contents the agent needs (e.g. reading numbers from a data file before computing).", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["path"]}}},
    "write_file": {"type": "function", "function": {"name": "write_file", "description": "Write text to a file. mode=create makes a new file (refuses if it exists), append adds to the end, write overwrites (requires allow_overwrite=True). Creates parent dirs.", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"},
        "mode": {"type": "string", "enum": ["create", "append", "write"]},
        "allow_overwrite": {"type": "boolean"}}, "required": ["path", "content"]}}},
    "search_files": {"type": "function", "function": {"name": "search_files", "description": "Recursively search a directory for files by name substring, extension, and/or content pattern. Returns up to 50 paths.", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "name": {"type": "string"}, "ext": {"type": "string"},
        "pattern": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["path"]}}},
```

2. `register_builtin_tools` 的 for 列表追加：

```python
        ("read_file", fs.read_file),
        ("write_file", fs.write_file),
        ("search_files", fs.search_files),
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_registry.py -v`
Expected: 全部 PASS（既有 8 + 新 1 = 9）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/tools/builtin.py tests/unit/test_registry.py
git commit -m "feat: register read_file/write_file/search_files as builtin tools"
```

---

### Task 5: MCP 包装

**Files:**
- Modify: `mio_cua/mcp_server.py`
- Test: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_mcp_server.py` 末尾追加：

```python
def test_mcp_read_file(tmp_path):
    from mio_cua.mcp_server import mcp
    p = tmp_path / "data.txt"
    p.write_text("12\n34\n56", encoding="utf8")
    content, _ = _run(mcp.call_tool("mio_read_file", {"path": str(p)}))
    assert "12" in content[0].text
    assert "56" in content[0].text


def test_mcp_write_file_create_and_refuse(tmp_path):
    from mio_cua.mcp_server import mcp
    p = tmp_path / "out.txt"
    c1, _ = _run(mcp.call_tool("mio_write_file", {"path": str(p), "content": "hello"}))
    assert "wrote" in c1[0].text
    assert p.read_text(encoding="utf8") == "hello"
    # create mode must refuse existing file
    c2, _ = _run(mcp.call_tool("mio_write_file", {"path": str(p), "content": "again"}))
    assert "refusing" in c2[0].text
    assert p.read_text(encoding="utf8") == "hello"


def test_mcp_search_files(tmp_path):
    from mio_cua.mcp_server import mcp
    (tmp_path / "alpha.txt").write_text("hello world", encoding="utf8")
    (tmp_path / "beta.md").write_text("hello world", encoding="utf8")
    content, _ = _run(mcp.call_tool(
        "mio_search_files", {"path": str(tmp_path), "name": "alpha"}))
    assert "alpha.txt" in content[0].text
    assert "beta.md" not in content[0].text
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_mcp_server.py::test_mcp_read_file -v`
Expected: FAIL（`mio_read_file` 工具不存在，工具列表里查不到）。

- [ ] **Step 3: 实现**

在 `mio_cua/mcp_server.py` 的 Filesystem tools 区域（`mio_move_files` 之后）追加 3 个工具：

```python
@mcp.tool(name="mio_read_file", annotations={
    "title": "Read a text file", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_read_file(path: str = Field(..., description="Path of the file to read"),
                        max_chars: int = Field(default=2000, description="Max chars to return", ge=1, le=100000)) -> str:
    """Read a text file's first N characters (default 2000). Use to retrieve
    file contents the AI needs (e.g. numbers to compute on) without opening the
    file in an editor."""
    from mio_cua.tools.fs import read_file
    return _run(read_file, path=path, max_chars=max_chars)


@mcp.tool(name="mio_write_file", annotations={
    "title": "Write text to a file", "readOnlyHint": False,
    "destructiveHint": True, "idempotentHint": False, "openWorldHint": True,
})
async def mio_write_file(path: str = Field(..., description="Path to write"),
                         content: str = Field(..., description="Text content to write"),
                         mode: str = Field(default="create", description="create/append/write"),
                         allow_overwrite: bool = Field(default=False, description="Allow overwriting an existing file in write mode")) -> str:
    """Write text to a file. mode=create makes a new file (refuses if it exists),
    append adds to the end, write overwrites only with allow_overwrite=True.
    Creates parent directories. Content is UTF-8."""
    from mio_cua.tools.fs import write_file
    return _run(write_file, path=path, content=content, mode=mode, allow_overwrite=allow_overwrite)


@mcp.tool(name="mio_search_files", annotations={
    "title": "Search files by name/ext/content", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_search_files(path: str = Field(..., description="Directory to search recursively"),
                           name: str = Field(default="", description="Filename substring (optional)"),
                           ext: str = Field(default="", description="Extension without dot, e.g. 'txt' (optional)"),
                           pattern: str = Field(default="", description="Content substring (optional)"),
                           max_results: int = Field(default=50, description="Max results", ge=1, le=500)) -> str:
    """Recursively search a directory for files by name substring, extension,
    and/or content pattern. Returns up to 50 matching paths."""
    from mio_cua.tools.fs import search_files
    return _run(search_files, path=path, name=name or None, ext=ext or None,
                pattern=pattern or None, max_results=max_results)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_mcp_server.py -v`
Expected: 全部 PASS（既有 15 + 新 3 = 18）。

- [ ] **Step 5: Commit**

```bash
git add mio_cua/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat: expose read/write/search files via MCP"
```

---

### Task 6: 全量回归 + README

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（预期 ~257 个）。

- [ ] **Step 2: README MCP 工具清单更新**

`README.md` 中「27 tools: file ops (`list_dir` / `make_dir` / `move_file` / `move_files`)」更新为：

```
file ops (`list_dir` / `read_file` / `write_file` / `search_files` / `make_dir` / `move_file` / `move_files`)
```

并把「27 tools」改为「30 tools」。

Commit：`git add README.md && git commit -m "docs: mention file content tools in MCP list"`

- [ ] **Step 3: 推送**

网络可用时 `git push origin master`。
