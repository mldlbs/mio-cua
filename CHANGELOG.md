# Changelog

All notable changes to mio-cua are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/). `Unreleased` holds in-progress
work; released sections are tagged on `master`.

---

## [Unreleased]

## [0.3.0] - 2026-08-22

### Added

- **文件内容工具** — 新增 `read_file` / `write_file` / `search_files` 三个确定性文件工具（零外部 SDK，仅标准库）：
  - `read_file(path, max_chars=2000)` 读取文本文件，超长截断并提示总数，二进制文件 fail（retryable）；上限钳制 100k。
  - `write_file(path, content, mode, allow_overwrite)` 支持 `create`（仅新建，拒绝覆盖）/`append`（追加，缺则新建）/`write`（覆盖，仅 `allow_overwrite=True`）；自动创建父目录。
  - `search_files(path, name, ext, pattern, max_results=50)` 递归搜索，`name`/`ext`/`pattern` 三过滤器 AND 组合，前 `limit` 条入结果、其余计 `more` 并提示 `...and N more`。
  - Agent / builtin / MCP 三通道注册；MCP 新增 `mio_read_file` / `mio_write_file` / `mio_search_files`。
- **文本选择能力** — 新增 `clipboard_get` / `clipboard_set` / `drag` / `select_element`（32 tools）：
  - `clipboard_get` 结构化返回 `{"text","has_text","length"}`，空剪贴板视为 success，OpenClipboard 失败才 retryable。
  - `clipboard_set(text)` 写入剪贴板，配合 `ctrl+v` 快速粘贴长文本。
  - `drag(x1,y1,x2,y2,element_id)`  primitive 拖拽；`element_id` 解析为 bbox 内缩（left+2 → right-2，mid-height），同时兼容 `obs.scene.nodes` 回退（OmniParser）。
  - `select_element(element_id)` composite 工具，基于 `drag` 横向拖选单行文本；Agent 侧闭环 `select → ctrl+c → clipboard_get` 校验。
  - `mio_cua/tools/{clipboard,drag,selection}.py` 新模块；`mcp_server.py` 薄包装重构，新增 `mio_select_element` / `mio_drag` / `mio_clipboard_*`。

### Fixed

- `tools/launch.py` — 裸域 URL（如 `example.com`）自动补 `https://` 解析到浏览器，避免被当成本地文件路径。
- `tools/selection.py` / `tools/drag.py` — `element_id` 解析增加 `scene.nodes` 回退，兼容 OmniParser 纯视觉控件 id 漂移。
- `tools/clipboard.py` — `OpenClipboard` 异常安全（try/finally 保证 CloseClipboard）。

### Changed

- `mcp_server.py: mio_drag` — 坐标直传时跳过 `Perception().observe()`，降低首帧开销（`perf: skip observe in coords-only mio_drag`）。

## [0.2.0] - 2026-08-15

### Added

- **Multi-step planner batching** — up to 3 tightly-related actions per plan,
  each re-verified against a fresh lightweight (OCR-only) observation before the
  next runs. Verification failure aborts the whole batch and replans with a
  GUIDANCE hint. Config: `batch_limit` (default 3), `batch_verify` (default True;
  `False` restores one-action-per-observation).
- **High-risk action confirmation** — delete / overwrite / kill_process /
  close_window now require an on-screen Yes/No confirmation before running;
  denial returns `retryable=False` (never retried) and timeout auto-denies
  (fail-closed). Disable with `MIO_CUA_CONFIRM_OFF=1`. Applies to the agent
  tool registry (schema `risk: "high"` + name-based fallback) and the MCP tools
  `mio_kill_process` / `mio_close_window`.
- **Screenshot → YAML scenario** — `mio-cua gen-scenario --image <png> | --capture`
  turns a real desktop screenshot into a YAML scenario (static element list);
  `mio-cua run "task" --simulate-scenario <scene.yaml>` replays it offline through
  the loop with no real input.
- **`mio_cua_GPU=0`** — forces OCR and layout-regions to CPU so onnxruntime /
  DirectML sessions don't run concurrently and spike VRAM.
- Promo assets (`promo/`), blog posts (`blog/`), marketing/growth docs, MIT
  LICENSE, and MCP Registry repository metadata.

### Fixed

- `scene/diff.py` — a curr node matched to a prev node by bbox but with a
  different id was falsely reported as "added" (int-vs-object comparison bug);
  broke scene diff accuracy whenever ids drifted.
- `agent/batch.py` OCR projection now reads observation *elements* (source
  "ocr") instead of scene nodes, so OCR glyphs folded into UIA nodes by
  NodeBuilder are not lost — full vs light frames diff symmetrically.
- `mio-cua run --simulate-scenario` now gives a friendly error on missing or
  malformed scenario YAML instead of a traceback; null element fields are
  tolerated.

## [0.1.5] - 2026-08-15

- MCP server sync to local sub-project repo; MCP Registry metadata.

## [0.1.2] - 2026-08-15

- OCR/vision made an optional extra.

## [0.1.1] - 2026-08-15

- README metadata, `server.json` for the MCP Registry.

[0.3.0]: https://github.com/mldlbs/mio-cua/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/mldlbs/mio-cua/compare/0.1.5...0.2.0
[0.1.5]: https://github.com/mldlbs/mio-cua/compare/0.1.2...0.1.5
[0.1.2]: https://github.com/mldlbs/mio-cua/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/mldlbs/mio-cua/compare/init...0.1.1
