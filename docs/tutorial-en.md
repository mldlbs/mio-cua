# mio-cua Quick Start (Windows)

A computer-use agent that sees your Windows screen and operates any app — like a human.
This tutorial walks through your first real task in ~5 minutes. Everything here has been
verified on Windows 11.

> **Prerequisites**: Windows 10+, Python 3.10+, an OpenAI-compatible API key
> (OpenAI, DeepSeek, etc.).

---

## 1. Install

```bash
pip install -e .            # core
pip install -e ".[vision]"  # + OCR (rapidocr_onnxruntime)
pip install -e ".[gpu]"     # + DirectML GPU acceleration for perception
```

> Run the terminal **as Administrator** on Windows — the agent needs permission to send
> real mouse/keyboard input and control windows.

## 2. Set your LLM key

PowerShell:

```powershell
$env:OPENAI_API_KEY = "sk-xxx"
```

Prefer a different provider or model? The agent is OpenAI-compatible — pass `--model` /
`--base-url`:

```powershell
# DeepSeek (works great and is cheap)
$env:OPENAI_API_KEY = "sk-xxx"
mio-cua run "打开计算器，计算 3*4" --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

Other knobs: `mio_cua_OCR_DEVICE=cpu` falls back to CPU OCR; `mio_cua_GPU=0` disables
DirectML GPU acceleration.

## 3. Smoke-test first (important)

The agent moves your **real mouse and keyboard**. Before a real task, run one tiny task
and confirm the **F9** emergency stop works:

```bash
mio-cua run "打开记事本，输入 hello"
```

Press **F9** at any time to stop.

## 4. Your first real task

```bash
mio-cua run "打开记事本，输入 hello world，等待 2 秒，然后截图"
```

You will see the mouse move by itself, the window focus change, and the text being typed.
Every step is saved to `~/.mio_cua/artifacts/` — the observation, the action taken, the
result, and an overlay screenshot with numbered element boxes.

### Plan without executing

```bash
mio-cua run "删除所有文件" --dry-run   # prints the plan, touches nothing
```

### Resume an interrupted task

```bash
mio-cua resume <task_id>
```

## 5. Cross-app workflow example

One instruction, three apps — read a file, sum numbers in Calculator, save the result:

```bash
mio-cua run "读取桌面 smoke_numbers.txt 中的数字（12/34/56），用计算器求和（102），保存到新文件 smoke_sum_result.txt"
```

## 6. Use it as an SDK

```python
from mio_cua import Agent, AgentConfig, Task

agent = Agent(AgentConfig(model="gpt-4o", max_steps=50))
result = agent.run(Task(instruction="打开记事本，输入 hello"))
print(result.status, result.steps)
```

## 7. Plug it into Claude / Cursor / ChatGPT (MCP)

`mio-cua` also ships as an MCP server — any MCP-capable client can control your desktop:

```json
{ "mcpServers": { "mio-cua": { "command": "mio-cua-mcp", "args": [] } } }
```

Then ask your assistant things like *"整理桌面上散落的文件，按类型归档"*.

## 8. Run the verification suite

Five end-to-end scenarios run on an **isolated virtual desktop** (your real desktop is
untouched):

```bash
python scripts/run_smoke_vdesk.py --only calculator,crossapp,explorer,notepad,web \
  --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

Logs: `%TEMP%\smoke_vdesk.log` (results reported as `[PASS]` / `[FAIL]`).

> Note: don't touch the mouse/keyboard for ~20 minutes while it runs, and make sure your
> desktop is unlocked.

---

## Safety checklist

- [ ] F9 emergency stop works
- [ ] Started with `--dry-run` first for anything destructive
- [ ] Task runs within step/time limits (`max_steps`, `task_timeout_s`)
- [ ] Audit trail on: every step screenshot is in `~/.mio_cua/artifacts/`

## Troubleshooting

| Symptom | Fix |
|---|---|
| No OCR / ImportError `rapidocr` | `pip install -e ".[vision]"` |
| Slow OCR | `pip install -e ".[gpu]"`; fall back with `mio_cua_OCR_DEVICE=cpu` |
| Window not found | Use `mio-cua run "..."` from an interactive session, or focus the window first |
| Unstable clicks | Re-run; the agent re-perceives the screen before every action |
| `+` key not typing in Calculator | The CLI sends it as a key event (`key(keys="+")`) — covered by the calculator scenario |

## Next steps

- Read the [blog intro](../blog/mio-cua-intro.md) for the philosophy
- Full MCP tool reference in [MCP.md](../MCP.md)
- Deep-dive: how the scene graph grounds actions — see the 5 verified scenarios in `smoke/`
