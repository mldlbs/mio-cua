# 截图自动生成 YAML 场景 — 设计文档

> 日期：2026-08-15
> 状态：已批准（子项目 3 of 3）
> 所属：mio-cua v0.2 milestone

---

## 1. 背景与问题

MockDesktop 的 notepad/calculator/explorer 场景是**手写硬编码**的（`simulation.py`），
元素坐标、文本与真实桌面可能偏差很大，且新增一个场景就要写代码。用户希望把**真实桌面
截图**自动转成可测试的场景定义，让离线模拟/冒烟测试贴近真实 UI。

**目标**：`mio-cua gen-scenario` 子命令把截图转成 YAML 场景（静态元素列表），
`mio-cua run --simulate-scenario <yaml>` 离线跑 loop，无真实输入。

## 2. 决策摘要（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 产出用途 | MockDesktop 风格的场景 YAML，供离线冒烟/模拟模式 |
| 入口 | CLI 子命令 `gen-scenario`（不做 MCP 工具） |
| 详细程度 | 静态元素列表（不做动作行为逻辑、不做多帧序列） |
| 消费方式 | 新增 `--simulate-scenario <yaml>` 参数加载 YAML 跑 loop（复用 ScriptedPerception/RecordingController） |
| 元素字段 | id / text / role / bbox 四字段；感知源：`--image` 仅 OCR，`--capture` merged（复用 Perception.observe） |

## 3. 架构与组件

### 3.1 YAML schema

```yaml
name: calculator            # 场景名
active_window: "计算器"      # 活动窗口标题
source: "ocr"               # 感知源：ocr（--image）| merged（--capture）
elements:
  - id: 0
    text: "0"
    role: "text"
    bbox: [400, 300, 240, 40]   # (left, top, width, height)
    source: "ocr"              # 单元素感知源（保留合并前的来源）
  - id: 1
    text: "7"
    role: "button"
    bbox: [400, 360, 50, 30]
    source: "ocr"
```

顶层 `source` 描述整份场景的来源（便于人读），单元素 `source` 保留原始来源
（merged 时可能是 ocr/uia/merged）。

### 3.2 新模块 `mio_cua/scenario.py`

职责：场景 dict 与 YAML / Observation / Element 之间的双向转换。

```python
def obs_to_scenario(obs, name="") -> dict:
    """Observation -> scenario dict (id/text/role/bbox/source per element)."""

def scenario_to_yaml(elements, active_window, name="", source="") -> str:
    """Element 列表 + 元信息 -> YAML 字符串。"""

def load_scenario_yaml(path) -> Observation:
    """YAML 文件 -> Observation（供 ScriptedPerception 消费）。"""
```

细节：
- `obs_to_scenario`：遍历 `obs.elements`，提取四字段 + 单元素 source，`active_window`
  取 `obs.active_window`。
- `scenario_to_yaml`：用 `yaml.safe_dump`（已有 PyYAML 依赖）序列化 dict；顶层
  `source` 由调用方传入（ocr/merged）。
- `load_scenario_yaml`：读文件 → `yaml.safe_load` → 校验 `elements` 存在 → 重建
  `Element(id, source, text, role, bbox)` 列表 → 返回
  `Observation(None, 1.0, active_window, 1.0, elements)`。
  - `bbox` 从 YAML list 转 tuple。
  - 顶层 `source` 传给每个 Element 的 `source`（若单元素无 source 字段）。
  - 缺 `active_window` 容错为 `""`；`elements` 缺失 → 返回空观察（不抛错）。

### 3.3 CLI 子命令（改 `mio_cua/cli.py`）

新增三个参数/子命令：

```
mio-cua gen-scenario --image <截图.png> [--name 场景名] -o out.yaml
mio-cua gen-scenario --capture [--name 场景名] -o out.yaml
mio-cua run "任务" --simulate-scenario <yaml>
```

- `gen-scenario`：
  - `--image <path>`：`Image.open(path)` → OCR（`ocr_module.get_elements`）→ 序列化
    （source="ocr"）。
  - `--capture`：`Perception().observe()` → merged elements → 序列化（source="merged"）。
  - `-o` 必填输出路径；`--name` 默认取文件 basename。
- `run --simulate-scenario <yaml>`：
  - 加载 YAML → `ScriptedPerception([obs])`（单帧，重复返回最后一帧）
  - `RecordingController`（`simulation.RecordingController`）
  - 复用 `simulation.build_simulation()`（已有，接线 loop + 安全 + 历史）
  - 跑 loop → 打印 status/steps/duration + 记录的 actions

### 3.4 复用现有模拟设施

`simulation.build_simulation(provider, system_prompt, script, registry, safety, events, config)`
返回 `(loop, controller)`，已支持任意 observation 脚本。`--simulate-scenario` 只需：
- `script = [obs]`（单帧静态场景）
- controller = `RecordingController()`
- 打印 `controller.calls` 作为「agent 会怎么做」的离线预览

## 4. 数据流

```
gen-scenario:
  截图.png ──OCR──> Element 列表 ──scenario_to_yaml──> out.yaml

run --simulate-scenario:
  out.yaml ──load_scenario_yaml──> Observation ──ScriptedPerception──> loop
                                                          (RecordingController, 无真实输入)
```

## 5. 错误处理与安全

- `--image` 文件不存在 / 无法打开 → 报错退出（非零码）。
- `load_scenario_yaml` 文件缺失 / YAML 非法 → 报错退出（非零码）。
- `gen-scenario` 需真实桌面（`--capture`）时若无活动窗口 → Perception.observe 已容错
  （rect=(0,0,0,0)），产物为空元素列表，照常输出。
- 模拟模式不发送真实输入（RecordingController），与现有 `--simulate-full` 一致。

## 6. 测试

### 6.1 单元（`tests/unit/test_scenario.py`）

- `scenario_to_yaml`：给定 Element 列表 → YAML 字符串，`yaml.safe_load` 后字段正确。
- `obs_to_scenario`：Observation → dict，四字段 + 单元素 source 保留。
- `load_scenario_yaml` round-trip：YAML → Observation → 元素完整（id/text/role/bbox）。
- `load_scenario_yaml` 缺 active_window → Observation.active_window == ""。
- `load_scenario_yaml` 缺 elements → 空 Observation（不抛错）。
- bbox 从 list 转 tuple。

### 6.2 集成（`tests/integration/test_cli.py`）

- `gen-scenario --image`：用合成 PNG（PIL 画几个框+文本）→ 产出有效 YAML，含 name/
  active_window/elements。
- `run --simulate-scenario`：用上面的 YAML → 跑 loop → 返回 TaskResult，无真实输入
  （RecordingController 断言无 SendInput 调用）。

### 6.3 CLI 测试（`tests/integration/test_cli.py` 或 unit）

- `--simulate-scenario` 缺失文件 → 非零退出 + 错误信息。

## 7. 不在范围内（YAGNI）

- 完整行为场景（动作 → 下一帧逻辑）。
- 多帧观察序列。
- 替换内置 MockDesktop 场景。
- MCP 工具 `mio_gen_scenario`（用户未选择）。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 静态场景无状态演化，loop 可能死循环 | 现有 Safety（max_steps/timeout）兜底；单帧重复返回最后一帧，agent 很快到 no_change/repeat hint 或 success |
| OCR 元素坐标是窗口相对 vs 屏幕绝对 | `--capture` 走 Perception.observe（已转屏幕坐标）；`--image` 仅用图片内坐标，模拟模式无屏幕依赖 |
| YAML 字段缺失导致加载崩溃 | `load_scenario_yaml` 逐字段容错（active_window/elements/source） |
| 与现有 `--simulate`/`--simulate-full` 混淆 | 新参数命名 `--simulate-scenario` 语义清晰，文档注明 |
