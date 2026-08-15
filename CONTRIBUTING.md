# Contributing to mio-cua

Thanks for helping! mio-cua gives AI eyes on the Windows desktop — every new
scenario that works is a win for everyone. Here's how to contribute well.

## Project layout

```
mio_cua/
  agent/        # AgentLoop, Planner, Safety, Recover, batch verification
  automation/   # win32 input backends, window/UIA helpers
  perception/   # OCR + UIA → Observation (with SceneGraph)
  scene/        # SceneGraph, node/relation/affordance builders, scene diff
  safety/       # high-risk tool list + user-confirmation gate
  tools/        # tool implementations + ToolRegistry
  vision/       # screenshot capture, OCR, overlay
  scenario.py   # screenshot → YAML scenario conversion
  mcp_server.py # MCP server exposing the tools
scripts/        # smoke runs, nightly regression, demo GIF
smoke/          # YAML scenario definitions (verified on real desktops)
tests/
  unit/         # fast, no real desktop needed
  integration/  # loop/CLI/planner against mocks
```

## Environment

- **Windows 10+** (the only supported platform today; run terminals as admin).
- Python 3.10+.
- Install core + extras:

```bash
pip install -e ".[vision]"   # core + OCR (rapidocr)
pip install -e ".[gpu]"      # + DirectML GPU acceleration
```

- Set your LLM key: `$env:OPENAI_API_KEY = "sk-..."` (any OpenAI-compatible
  provider works; `deepseek-v4-flash` is cheap enough for all scenarios).

## Development workflow

1. **Branch off `master`**, give it a descriptive name (`feat/...`, `fix/...`).
2. **Write a failing test first** (TDD). Keep tests fast — unit tests must not
   touch a real desktop or call an LLM.
3. **Implement the minimal change**, then make the test pass.
4. **Run the full suite** before committing:

```bash
python -m pytest -q
```

5. **Commit** with a concise message matching repo style
   (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
6. Push and open a PR. Keep the PR scoped to one feature or fix.

## Safety rules (non-negotiable)

- New tools that delete/overwrite/kill/close **must** be marked high-risk:
  add the semantic key to `mio_cua/safety/risk.py::HIGH_RISK` AND set
  `"risk": "high"` in the tool schema (`mio_cua/tools/builtin.py`), or — for
  MCP tools — add the name to `mio_cua/mcp_server.py::_MCP_HIGH_RISK`.
- Never bypass the confirmation gate. It's fail-closed by design: a timeout or
  dialog error denies the action.
- Changes to the agent loop must keep `batch_verify=False` / `batch_limit<=1`
  as a working fallback (one-action-per-observation).
- Audit trails stay intact: screenshot-per-step artifacts are produced by full
  observations; lightweight `observe_light()` must not write artifacts.

## Adding a smoke scenario

Scenarios in `smoke/*.yaml` are the "verified on a real Windows desktop" set.
The format (see `smoke/calculator.yaml`):

```yaml
id: calculator
title: "Human-readable description"
instruction: >-
  The exact natural-language task to run (what a user would type).
timeout_s: 240
max_steps: 40
checks:
  - type: active_window
    contains: 计算器
```

Run one or more scenarios on an **isolated virtual desktop**:

```bash
python scripts/run_smoke_vdesk.py --only calculator,notepad,explorer \
  --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

A scenario only "passes" when its `checks` hold on a real desktop. If an app
resists, prefer deterministic channels (filesystem tools, `key` shortcuts,
`launch`/`focus_window`) over pixel clicks in the instruction.

## Debugging offline (no real desktop, no LLM)

- `mio-cua run "任务" --simulate-scenario <scene.yaml>` replays a scenario
  offline through the loop (no real input). Generate a scene from a screenshot:

```bash
mio-cua gen-scenario --image shot.png --name calc -o calc.yaml
```

- `mio-cua replay <task_id>` replays every step from saved artifacts.

## Code style

- Python 3.10+ type hints on public functions.
- No comments unless they explain a non-obvious "why".
- Follow the module docstring conventions of the file you touch.
- Keep files focused (one responsibility); prefer small modules over large ones.

## Tests

- Unit tests: `tests/unit/` — mock perception/LLM, never touch the desktop.
- Integration tests: `tests/integration/` — loop + planner + CLI against
  scripted/mock desktops.
- Run everything before pushing: `python -m pytest -q`.

## Need help?

Open an issue for bugs, "my app can't be automated yet" reports, or questions.
Every new scenario added to `smoke/` is a contribution.
