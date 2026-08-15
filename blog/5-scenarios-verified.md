# From 0 to cross-app: the 5 scenarios we verify on every commit

> Draft for dev.to / Medium. Repo: https://github.com/mldlbs/mio-cua

---

A computer-use agent that only works in a demo video isn't a product — it's a screensaver.
The way mio-cua stays honest is a **release-gate smoke suite**: five end-to-end scenarios
that run against the *real* Windows desktop, on every meaningful change.

This post is about that suite: what the five scenarios are, how a scenario is defined,
and the checks that keep the agent from faking success.

## The five scenarios

| id | What it verifies | Artifact checks |
|---|---|---|
| `notepad` | open, type `hello world`, Ctrl+S, save as | file exists + contains `hello world` |
| `calculator` | keyboard input `123*456=`, display shows `56088` | active window is Calculator |
| `explorer` | Win+E, Ctrl+Shift+N, name folder, Enter | folder exists on Desktop |
| `crossapp` | read file → Calculator sum → save result | file exists + contains `102` |
| `web` | open a local HTML page, click & type, purely visual | result confirmed on screen |

Together they cover the whole capability surface: single-app input, dialog handling,
file system, cross-application data flow, and DOM-free web.

## A scenario is just a YAML file

Each scenario in `smoke/*.yaml` is data, not code:

```yaml
id: calculator
title: "计算器：计算 123*456"
instruction: >-
  打开计算器程序，用键盘逐个按键输入表达式 123*456=...
  每按一键后确认计算器显示区更新，按完 = 后确认显示 56088，
  然后调用 success 工具。
timeout_s: 240
max_steps: 40
checks:
  - type: active_window
    contains: 计算器
```

The `instruction` is the natural-language task (also how you'd use the SDK), and
`checks` are the *ground truth*. New scenarios are additive — the suite gets stronger
with every app someone contributes.

## The checks are where it stops lying

`status=SUCCESS` from the agent is **not** enough. The runner enforces:

1. **Artifact checks must pass.** A `file_exists`/`dir_exists`/`file_contains` rule
   must be true, or the scenario FAILs even if the agent claimed success:

```python
if artifact_checks:
    passed = passed and all(artifact_checks)
```

2. **Window checks confirm context.** The `active_window` check makes sure the agent is
   actually where it claims to be (e.g. Calculator, not a stray window).

3. **Stale apps are killed between scenarios.** A leftover Calculator from the previous
   run gets reused by the next scenario, and the agent starts clicking *it* instead of
   following the new task. `_kill_stale_apps()` force-closes notepad/calc/paint —
   deliberately **not** browsers, which share processes with the user's real windows.

## Running it never touches your real desktop

The default runner moves the mouse on whatever desktop is foreground. That's fine for a
single scenario, but the **vdesk** runner is the real answer: it runs the whole suite on
a dedicated virtual desktop (desktop #2, marked by a hidden window), so your working
desktop is never touched.

```bash
python scripts/run_smoke_vdesk.py --only calculator,crossapp,explorer,notepad,web \
  --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

Logs go to `%TEMP%\smoke_vdesk.log`; results print as `[PASS]` / `[FAIL]`.

## The results (2026-08-08)

- `crossapp`: **21 steps, SUCCESS**, artifact checks green
- `calculator` / `explorer` / `notepad` / `web`: all PASS
- Model: **deepseek-v4-flash** — the suite doubles as a cost test

## Why "verified on every commit" matters

The value isn't the one-time pass — it's the **regression gate**. When you change the
perception pipeline (say, the OCR/UIA merge heuristic), you don't find out weeks later
that the calculator no longer reads digits. You find out on the next `run_smoke`.

That's the difference between "a cool demo" and "something you can hand to someone and
say *run it*."

Try the suite yourself:
https://github.com/mldlbs/mio-cua
