# mio-cua

Mio Computer-Use Agent：Windows 桌面自动化 AI Agent（Python SDK + CLI）。

<!-- mcp-name: io.github.mldlbs/mio-cua -->

## 安装

```bash
pip install -e .        # 从源码安装（依赖见 pyproject.toml）
# Windows 下建议以管理员身份运行
```

### 配置

设置 LLM API Key：

```bash
set OPENAI_API_KEY=sk-xxx        # Windows CMD
$env:OPENAI_API_KEY = "sk-xxx"   # PowerShell
```

示例脚本还支持 `DESKTOP_AGENT_PROVIDER` / `DESKTOP_AGENT_MODEL` 环境变量覆盖模型。

### 当前状态

v0.5：Scene Graph 感知层 + 网页纯视觉感知（Regions 版面 + OmniParser 控件识别）；五个端到端场景（记事本/计算器/资源管理器/跨应用/网页）已在真实 Windows 11 桌面完成 5/5 全绿终验（2026-08-08）。

- **Scene Graph 感知层**：感知层把 OCR+UIA 融合为一张场景图（`mio_cua/scene/`）——每个 UI 对象是一个 Node（类型/文本/状态/bbox），配空间关系（leftOf/above/labelFor）和 **Action candidates**（感知层已验证的可点击动作，如 `click node 7 ('7') {'value': '7'} expects {'display': True}`）。LLM 从候选动作里选择，不再自行推断坐标/UI。
- **网页纯视觉感知（像人一样上网）**：浏览器窗口额外走两条视觉链路，不依赖 DOM——
  - **Regions 版面分析**（`rapid_layout`，可选依赖）：识别页面结构（导航/标题/正文/表格/图片区域），可选依赖未装则优雅降级。
  - **OmniParser 控件识别**（`scene/omniparser.py`，可选依赖）：YOLOv9 交互元素检测 + Florence-2 语义描述，把网页截图解析成按钮/链接/输入框（`button`/`text` 节点 + 可点击候选）。需 torch CUDA；模型默认在项目内 `models/omniparser/`，也可用 `OMNIPARSER_DIR`/`OMNIPARSER_WEIGHTS` 环境变量覆盖。
- **显示区验证**：计算器显示区被识别为 `display` 节点，点击数字键后通过 Scene Diff 检测显示值变化（`0`→`7`），用于动作成功校验。
- **跨应用（crossapp）场景**：`smoke/crossapp.yaml`——读 `smoke_numbers.txt`（12/34/56）→ 计算器求和 102 → 保存 `smoke_sum_result.txt`。全绿验收（2026-08-08，19-21 步）。关键修复：**一动作一感知**（每步重新感知再决策，避免多动作基于陈旧场景执行）；**计算器 `+` 键发送**（`key(keys="+")` 曾被当分隔符 split 失败）；**UWP 计算器聚焦**；其余见 SMOKE.md 修复链。
- **网页纯视觉场景（web）**：`smoke/web.yaml`——Edge 打开本地 HTML，纯视觉（OmniParser，不接 DOM）点击按钮/输入文本并视觉确认。PASS（2026-08-08，9 步 165s）。OmniParser 走本地 HF 缓存离线推理（`HF_HUB_OFFLINE=1`，首帧加载约 20s，后续每帧 ~0.3s）。
- **完整套件**：calculator/crossapp/explorer/notepad/web 五场景全绿终验（2026-08-08，crossapp 21 步 SUCCESS、其余 SUCCESS/校验通过）。deepseek-v4-flash 即可完成。调优中修复 6 个工程 bug（陈旧场景执行、UWP 聚焦、`+` 键 split、浏览器 PATH、重命名引导、元素 id 稳定）。
- **GPU OCR**：经 DirectML（onnxruntime-directml）加速，单次 OCR 平均 ~1.6s；`DESKTOP_AGENT_OCR_DEVICE=cpu` 可回退纯 CPU。
- **窗口区域截图**：只抓活动窗口区域（而非全屏），截图体积缩减约 80%，更聚焦目标窗口。
- **Artifact 自动清理**：任务结束后自动修剪，目录默认上限 200MB（配置项 `artifact_max_bytes`）。
- **循环守卫**：动作无变化 / 重复相同动作 ≥6 次直接判定 FAIL，避免空转。
- **真实验收（deepseek-v4-flash + DirectML）**：记事本（输入并保存 `hello world`）、计算器（`123*456=56088`）、资源管理器（新建并重命名 `smoke_demo_folder`）三个场景全部 PASS。

发送给 LLM 的截图带编号框（overlay），编号与元素列表 `id` 一一对应。每步操作与截图会落盘为 artifact，任务状态支持 `resume`。可重试失败会自动触发 Recovery（聚焦窗口后重试，每次 action 最多重试 2 次）。

> 提示：首次在真实桌面运行前，请先完成一次小任务的冒烟测试（如"打开记事本输入 hello"），并确认 F9 急停可用。冒烟测试见 `SMOKE.md`。

## CLI

```bash
mio-cua run "打开计算器，计算 3*4" --model gpt-4o
mio-cua run "删除所有文件" --dry-run    # 只打印计划，不执行
mio-cua resume <task_id>                # 从上次状态重新执行任务
mio-cua replay <task_id>                # 从 artifact 回放任务步骤（调试用，--full 显示参数）
mio-cua providers
```

## Artifacts / 状态

- 每步：`~/.mio_cua/artifacts/<ts>.json`（observation + action + result）
- 每步截图：`~/.mio_cua/artifacts/<ts>.png`（overlay 标注图）与 `.raw.png`
- 任务状态：`~/.mio_cua/artifacts/state/<task_id>.json`

## SDK

```python
from mio_cua import Agent, AgentConfig, Task

agent = Agent(AgentConfig(model="gpt-4o", max_steps=50))
result = agent.run(Task(instruction="打开记事本，输入 hello"))
print(result.status, result.steps)
```

## MCP（接入 Claude / Cursor / ChatGPT）

mio-cua 也作为 **MCP server** 暴露，让任意 MCP 客户端直接控制桌面：

```bash
pip install -e .
```

```json
{ "mcpServers": { "mio-cua": { "command": "mio-cua-mcp", "args": [] } } }
```

10 个工具：文件操作（list_dir/make_dir/move_file/move_files）、窗口（launch/focus_window/get_active_window）、输入（click/type/key）。详见 [MCP.md](MCP.md)。

## 安全

- F9 急停
- 步数上限 / 任务超时
- 每步截图留痕（artifact）

## 验收套件（smoke）

五个端到端场景在**独立虚拟桌面**上隔离运行，不打扰主桌面：

```bash
# 完整套件（calculator/crossapp/explorer/notepad/web）
python scripts/run_smoke_vdesk.py --only calculator,crossapp,explorer,notepad,web --model deepseek-v4-flash --base-url https://api.deepseek.com/v1

# 单场景
python scripts/run_smoke_vdesk.py --only crossapp --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

运行前需：`$env:OPENAI_API_KEY="sk-xxx"`；桌面已解锁；用户约 20 分钟不碰键鼠（vdesk 隔离在用户操作时失效）。日志 `%TEMP%\smoke_vdesk.log`，结果以 `[PASS]/[FAIL]` 汇总。

前置文件：`~/Desktop/smoke_numbers.txt`（12/34/56，crossapp 输入）、`~/Desktop/vision_test.html`（web 测试页）。场景间自动清理测试应用进程。

- 判定规则：`status=SUCCESS` 且（若场景有产物校验）所有 file/dir/contains 校验通过才算 PASS——防止 agent 假 success。
- 收尾提示：屏幕稳定且已按 Enter/Save 确认后，提示 agent 调 `success`，避免任务完成却超时。
