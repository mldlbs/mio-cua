# 通用可验证证据报告工作流 — 设计 Spec（MVP）

> 状态：draft | 日期：2026-08-22 | 基于：mio-cua 0.3.0（`mio-cua/tools/fs.py:91` / `mio_cua/tools/selection.py:14` / `mio_cua/scene/builder.py:1`）
> 实例：微信群 `兴蓉` 近一周整理（`smoke/wechat_兴蓉整理.md`）仅为 Runtime 上下文，非能力定义

## 1. 目标

把“列表→筛选→提取→落盘”类需求（如微信消息整理）从自动化脚本提升为**可验证 Agent 工作流**：输入 `app/keyword/time/output`（`app` 仅为 Runtime 上下文），输出带来源链的 **Markdown 证据报告**，每步可观测、可恢复、可验证。能力本身不认识微信，Runtime 才知道当前操作的是哪个应用。MVP 聚焦 4 项：搜索发现+人工勾选、clipboard 长文本采集、artifact 留痕、证据报告。

## 2. 非目标（MVP 外）

- OCR 主路径、UIA text range 深度、增量游标同步、回写微信

## 3. 总体架构（单 Runtime 三阶段）

```
Task{app,keyword,time_range,output} // app 仅为 Runtime 上下文
  ↓
Discovery → Candidate[] + artifact
  ↓
Human Confirmation (must) → Selected[]
  ↓
Extraction → Dataset + artifact
  ↓
Validation → EvidenceReport + validation artifact
```

* 单 runtime 驱动三 stage，但三 stage 仅为 **业务 Goal State**，非执行流程；底层始终为 **闭环 Agent Loop** `Observe→Plan(action+expected_state)→Act→Observe→Verify(expected_state,observation)→Re-plan/Recovery`，以 `mio_cua/agent/loop.py` 为底座，符合 `mio-cua` “一动作一感知”（`batch_verify`）
* 每 stage 产结构化状态 + artifact（截图/场景图/`observation_id`）
* **分层原则**：`MCP/Core Capability {mio_discover,mio_extract,mio_validate,mio_report}` 不出现 `wechat`；底层为应用无关 UI 能力 `search_input/candidate_list/select_candidate | scroll/select/clipboard/OCR | visual_compare/completeness_check | dataset→evidence`
* **架构原则**：**能力不认识微信，Runtime 才知道**
* **架构约束**：`Core/Workflow` **不得通过 `app` 分支实现应用特化逻辑**，禁止 `if app == "微信": ... elif app == "钉钉": ...`；`app` 仅用于 Runtime **选择/定位当前 UI 上下文**（`app/window/scene`），不得改变 `discover/extract/validate/report` 的语义、数据模型或执行协议。依赖关系：
  ```
  User Task → Runtime Context(app/window/scene) → Generic Workflow(Goal State: Discover→Human Confirm→Extract→Validate→Report) → Evidence
                 ↓
            Agent Loop(Observe→Plan→Act→Observe→Verify→Re-plan)
  ```
  换成浏览器/钉钉/QQ/任意桌面应用，核心代码无需新增应用分支
* **Verify 定义**：`Verify` 非判断 `Act` 是否 `success`，而是判断 **当前世界状态是否满足下一步规划前提**（`Verify(expected_state, observation)` → `satisfied/changed/failed→Recovery`）
* **最严格一动作一感知**：**任何 Action 的执行结果都不能作为下一 Action 的事实依据；下一 Action 只能依据 Action 后的新 Observation 决策**

## 4. 三不变量（强制）

1. **Discovery 不允许直接进入 Extraction**：必须存在 `HumanConfirmState{selected_ids, timestamp}`
2. **Extraction 不允许宣称成功**：必须经过 `Validation`，`Validation` 未通过不得标记 `completed`
3. **Validation 失败不能覆盖原始 artifact**：仅产生新 `validation_result` / 重试轨迹，原始 `MessageDataset`  immutable

## 5. 阶段设计

### 5.1 Discovery（应用无关）

- **输入**：`app`（Runtime 上下文，如 `微信`）、`keyword`（如 `兴蓉`）、`time_range` 仅作展示
- **实现（通用 UI 能力）**：`search_input`（聚焦应用 → 搜索框输入 keyword）→ `candidate_list`（`observe()` 解析列表）→ `select_candidate` → 输出 `Candidate[]{name,avatar,last_message_time,member_count,confidence,screenshot,observation_id}`
- **输出**：`discovery.json` + 截图
- **不变量**：输出前必须落盘，未经用户勾选不得进入下一阶段

### 5.2 Human Confirmation

- UI：展示 `Candidate` 表格，用户勾选 `Selected[]`
- 状态：`confirm.json`，无此文件 `Extraction` 拒绝执行

### 5.3 Extraction（应用无关，P0 clipboard）

- **输入**：`Selected[]`
- **优先级**：`P0 clipboard > P1 UIA text range > P2 select_element > P3 OCR fallback`，MVP 仅实现 P0 + artifact，P1-P3 为扩展点
- **通用 UI 能力**：`scroll` / `select` / `clipboard` / `OCR`；流程 per item：`focus → click candidate` → 详情区 `select` 全选 → `ctrl+c` → `clipboard_get` 结构化文本 → 解析 `timestamp/sender/content` → 去重（MVP 按 `timestamp+sender+content` 文本去重）→ `Record[]{timestamp,sender,content,source{id,screenshot,observation_id,extraction_method},confidence}`
- **Artifact**：每项 `extraction_{id}.json` + 截图

### 5.4 Validation（应用无关）

- **通用能力**：`visual_compare` / `completeness_check`
- 校验：消息数、时间窗覆盖、`confidence<0.85` 标黄、是否 `...and N more` 未展开
- 输出：`validation.json{status, issues[]}`，`status=failed` 时仅追加，不覆盖 `Dataset`
- 失败则产生重试轨迹，回 `Extraction` 重采

### 5.5 Evidence Report（应用无关）

- **输出**：`dataset → evidence`，实例产物 `smoke/wechat_兴蓉整理.md`（监测测试夹子，仅为测试实例）
- **结构**：
  ```md
  # 监测报告（app=微信, keyword=兴蓉）
  ## 扫描摘要 |候选|消息数|状态|置信度|
  ## 异常 - 未展开/OCR失败/页面变化
  ## 消息 [HH:MM] sender: content
  ```
- 审计属性：每条记录可回放 `source.screenshot`/`observation_id`

## 6. 与 mio-cua 现有能力映射

- 感知：`Perception().observe()` + `DmlExecutionProvider`（`C:\d\venvs\mio-gpu` 已验证）
- 动作：`focus_window`/`click`/`scroll`/`select_element`/`key(ctrl+c)`/`clipboard_get`/`write_file`
- 安全：`F9`急停、`--dry-run`、`MIO_CUA_CONFIRM_OFF`、artifact 留痕

## 7. MVP 验收

1. 搜索 `兴蓉` → 展示候选群（≥2）→ 用户勾选
2. 勾选群近一周消息落盘至 `smoke/wechat_兴蓉整理.md`，含来源链
3. `Validation` 通过才标记成功，失败留痕不覆写
4. 全流程可在 `mio-cua-mcp`（`C:\d\venvs\mio-gpu\Scripts\mio-cua-mcp.exe`）以单 runtime 复现

## 8. 二阶段扩展点

- `P1 UIA` / `P3 OCR` 回退、`SyncCursor{last_message_hash,last_visible_position}` 增量、`Message Provenance` 完整链
