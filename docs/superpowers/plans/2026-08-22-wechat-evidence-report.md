# 通用可验证证据报告工作流 — 实现计划（MVP）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 或 superpowers:executing-plans 按 Task 逐项落地。Spec 见 `docs/superpowers/specs/2026-08-22-wechat-evidence-report-design.md`
> 实例产物 `smoke/wechat_兴蓉整理.md` 仅为测试实例，能力本身不认识微信

**Goal:** 单 runtime 三阶段 `Discovery→Human Confirmation→Extraction→Validation→Evidence Report`，MVP 实现 4 项：搜索发现+人工勾选、clipboard 长文本采集、artifact 留痕、Markdown 证据报告；能力为通用 UI 能力 `search_input/candidate_list/select_candidate | scroll/select/clipboard/OCR | visual_compare/completeness_check | dataset→evidence`，`app` 仅为 Runtime 上下文（如 `app="微信", keyword="兴蓉"` 落盘 `smoke/wechat_兴蓉整理.md`）。

**Architecture:** 新增 `mio_cua/workflow/` 包（`discovery.py`/`extraction.py`/`validation.py`/`report.py`/`state.py`），复用 `mio_cua/perception` + `mio_cua/tools/{clipboard,selection,fs}` + `mio_cua/mcp_server.py` 薄包装；`MCP/Core Capability {mio_discover,mio_extract,mio_validate,mio_report}` 不出现 `wechat`；不变量由 `state.py` 强制（无 confirm 不进 Extraction，未经 Validation 不算成功，失败不覆写）。无 `adapters/wechat/`。

**Tech Stack:** Python 3.12, `pynput`/`pywin32`, `rapidocr` (DML), `pytest`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `mio_cua/workflow/state.py` | 三阶段状态 + 不变量校验 | **Create** |
| `mio_cua/workflow/discovery.py` | `search_input`→`candidate_list` → Candidate[] | **Create** |
| `mio_cua/workflow/extraction.py` | `scroll/select/clipboard` → Record[] | **Create** |
| `mio_cua/workflow/validation.py` | `visual_compare/completeness_check` → validation.json | **Create** |
| `mio_cua/workflow/report.py` | `dataset→evidence` Markdown 生成 | **Create** |
| `mio_cua/workflow/__init__.py` | 包初始化 | **Create** |
| `mio_cua/mcp_server.py` | 新增 `mio_discover`/`mio_extract`/`mio_validate`/`mio_report`（不含 wechat） | Modify |
| `tests/unit/test_workflow_state.py` | 不变量单测 | **Create** |
| `tests/unit/test_workflow_discovery.py` | Discovery 单测（mock observation, app=微信 keyword=兴蓉） | **Create** |
| `tests/unit/test_workflow_extraction.py` | Extraction 单测（mock clipboard） | **Create** |
| `tests/unit/test_workflow_validation.py` | Validation 单测 | **Create** |
| `tests/unit/test_workflow_report.py` | Report 单测（实例落盘 `smoke/wechat_兴蓉整理.md`） | **Create** |

---

### Task 1: `mio_cua/workflow/state.py` — 状态与不变量

**Files:**
- Create: `mio_cua/workflow/state.py`
- Test: `tests/unit/test_workflow_state.py`

- [ ] **Step 1: 写失败测试** `tests/unit/test_workflow_state.py`（校验三不变量：无 confirm 不进 Extraction 等）
- [ ] **Step 2: 运行确认失败** `python -m pytest tests/unit/test_workflow_state.py -v` → FAIL
- [ ] **Step 3: 实现** `state.py`（`DiscoveryState`/`ConfirmState`/`ExtractionState`/`ValidationState` + `assert_can_extract`/`assert_can_complete`）
- [ ] **Step 4: 运行确认通过** `python -m pytest tests/unit/test_workflow_state.py -v` → PASS
- [ ] **Step 5: Commit** `feat: add workflow state with invariants`

---

### Task 2: `mio_cua/workflow/discovery.py`（通用）

**Files:**
- Create: `mio_cua/workflow/discovery.py`
- Test: `tests/unit/test_workflow_discovery.py`

- [ ] **Step 1: 写失败测试**（mock `Perception().observe()` 返回含 `兴蓉` 的 `Element`，断言 `discover(app="微信", keyword="兴蓉")` 返回 `Candidate[]` 含 `confidence`/`bbox`）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（通用 `search_input` → `candidate_list`：`focus_window(app)` → 搜索框 `type(keyword)` → `observe()` → 过滤 → 产 `Candidate[]` + 写 `discovery.json` + 截图 artifact；`app` 仅 Runtime 上下文）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: add generic discovery via search`

---

### Task 3: `mio_cua/workflow/extraction.py` — 通用 clipboard P0

**Files:**
- Create: `mio_cua/workflow/extraction.py`
- Test: `tests/unit/test_workflow_extraction.py`

- [ ] **Step 1: 写失败测试**（mock `select` + `clipboard_get` 返回结构化文本，断言 `extract(id)` 产 `Record{source{observation_id,extraction_method="clipboard"}}`）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（通用 `scroll/select/clipboard`：`click candidate` → `select` 全选 → `key(ctrl+c)` → `clipboard_get` → 解析 `timestamp/sender/content` → 去重 → 写 `extraction_{id}.json`，不变量：无 `ConfirmState` 抛错）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: add generic clipboard extraction`

---

### Task 4: `mio_cua/workflow/validation.py`（通用）

**Files:**
- Create: `mio_cua/workflow/validation.py`
- Test: `tests/unit/test_workflow_validation.py`

- [ ] **Step 1: 写失败测试**（`validation` 对空/低置信/未展开场景应 `failed` 且不覆盖原 `Dataset`）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（通用 `visual_compare/completeness_check`：校验消息数/时间窗/`confidence<0.85` 标黄，产 `validation.json`，失败仅追加）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: Commit** `feat: add generic validation with immutable artifact`

---

### Task 5: `mio_cua/workflow/report.py` + MCP 包装 + 全量回归（通用）

**Files:**
- Create: `mio_cua/workflow/report.py`
- Modify: `mio_cua/mcp_server.py`
- Test: `tests/unit/test_workflow_report.py`, `tests/unit/test_mcp_server.py`

- [ ] **Step 1: 写失败测试**（`report(Selected[], Dataset, validation.json)` 生成 `smoke/wechat_兴蓉整理.md`（实例产物）含扫描摘要/异常/消息三段）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** `report.py`（`dataset→evidence`）+ `mcp_server.py` 新增 `mio_discover`/`mio_extract`/`mio_validate`/`mio_report` 薄包装（`_run` 委托，不含 wechat）
- [ ] **Step 4: 运行确认通过** `python -m pytest -q` 全绿
- [ ] **Step 5: Commit** `feat: add generic evidence report and MCP wrappers` + `docs: mention workflow`

---

## 验收

- `C:\d\venvs\mio-gpu\Scripts\python.exe -m pytest -q` 全绿
- 真机（通用，`app` 为 Runtime 上下文）：`mio_discover(app="微信", keyword="兴蓉")` → 人工勾选 → `mio_extract` → `mio_report` 落盘 `smoke/wechat_兴蓉整理.md`（实例），`Validation` 未过不算成功
