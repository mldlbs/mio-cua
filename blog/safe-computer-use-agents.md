# Safe computer-use agents: emergency stop, audit trails, virtual desktops

> Draft for dev.to / Medium. Repo: https://github.com/mldlbs/mio-cua

---

An agent that moves your real mouse and keyboard is a privilege. Give it the same
attention as the model plumbing — the "boring 50%" of a computer-use agent is everything
that keeps it from doing damage while it learns.

Here's the safety stack in mio-cua, from the operator's finger to the filesystem.

## 1. F9 emergency stop (and it must be testable)

The first line of defense is a hotkey listener that flips a flag checked between steps:

```python
from pynput import keyboard

def on_press(key):
    name = getattr(key, "name", None)
    if name == self.emergency_key or char == self.emergency_key:  # "f9"
        self._stopped = True
```

Important details:

- The listener is **daemon** — if anything else crashes, it doesn't block shutdown.
- If the hotkey can't register (headless session, weird terminal), it logs a warning
  instead of failing silently — you'll know you don't have a panic button.
- The README's Quick Start tells users to **test F9 on a one-line task before trusting
  the agent** with anything real. A safety feature you've never exercised is a feature
  that doesn't exist.

## 2. Step limits and timeouts — always on

The loop consults `Safety.should_stop()` before every observation and every action:

```python
if self._stopped:                    return True
if self.step_count >= self.max_steps: return True
if time.time() - self._started_at > self.timeout_s: return True
```

Default: 50 steps / 300s. Bounded loops mean a confused agent can burn budget but not
the machine. `status()` distinguishes `ABORTED` (hit a limit / emergency stop) from
`TIMEOUT` so the failure reason is diagnosable.

## 3. Screenshot-per-step audit trail

Every step writes:

- `observation + action + result` JSON (`~/.mio_cua/artifacts/<ts>.json`)
- an overlay screenshot with numbered element boxes (`<ts>.png`)
- the raw capture (`<ts>.raw.png`)

This is the agent's black box: after anything happens, you can replay exactly what it
saw, decided, and did — including which element id it clicked and whether that "succeeded".
`mio-cua replay <task_id>` renders that transcript.

Storage is bounded (`artifact_max_bytes`, default 200MB) and pruned automatically, so
the trail can't fill your disk.

## 4. `--dry-run`: preview plans, touch nothing

```bash
mio-cua run "删除所有文件" --dry-run   # prints the plan, does nothing
```

Before any destructive instruction, the plan is inspectable. It's one flag — but it's
the difference between "trust me" and "show me first".

## 5. Filesystem refusal to overwrite

File moves are explicitly guarded: **moving a file never overwrites an existing target.**
A "sort my desktop" agent that would happily clobber two files with the same name gets a
deterministic failure instead. This is the class of bug you don't want to discover by
losing data.

## 6. Verification guards against "fake success"

The agent can claim success when the work didn't actually land. Two loop-level guards
target the classic cases:

- **Unconfirmed edits**: a `type` without an `element_id` (a focused rename box /
  filename field) is not applied until Enter. If the agent calls `success` without
  confirming, the loop **blocks it** and instructs it to press Enter first.
- **Loop / no-op detection**: repeated identical actions ≥6 times, or a screen that
  never changes, trips an explicit FAIL instead of spinning forever.

## 7. Isolated virtual desktops for testing

The five end-to-end scenarios run on a **dedicated virtual desktop** (`scripts/vdesk.py`),
not your real one. The smoke runner:

- reuses one marker-identified test desktop (desktop #2) instead of piling up new ones,
- kills stale apps left by previous runs (notepad/calc/paint/edge),
- detaches the run so a crash doesn't take the terminal with it.

Result: you can validate the agent against real apps without it ever touching your
working desktop.

## The lesson

The interesting part of a computer-use agent is the perception and the loop. The
*responsible* part is:

1. a panic button you've actually tested,
2. hard limits that can't be disabled accidentally,
3. an audit trail that answers "what did it do?",
4. a preview mode for destructive commands,
5. guardrails against false completion,
6. isolation from your real environment.

None of it is glamorous. All of it is why you'd let the thing drive.

Repo: https://github.com/mldlbs/mio-cua
