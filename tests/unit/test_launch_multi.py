from types import SimpleNamespace

from mio_cua.tools import launch as launch_mod


class _Ctx:
    current_action_id = "a-1"


def test_launch_notepad_opens_fresh_window_not_reuse(monkeypatch):
    """A bare `launch notepad` must start a new instance (multi-instance app),
    not silently reuse a window already showing an old file."""
    ctx = _Ctx()
    calls = []

    monkeypatch.setattr(launch_mod.subprocess, "Popen", lambda cmd, shell=True: calls.append(cmd) or True)
    monkeypatch.setattr(launch_mod, "_wait_for_front", lambda cmd, tries=6, delay=1.0: True)

    res = launch_mod.launch(ctx, "notepad")
    assert res.success
    assert calls == ["notepad"], f"expected a fresh Popen for notepad, got {calls}"
    assert "reused" not in res.message


def test_launch_calc_still_reuses_existing_window(monkeypatch):
    """Single-instance apps keep the reuse fast-path: no duplicate process."""
    ctx = _Ctx()
    calls = []

    monkeypatch.setattr(launch_mod.subprocess, "Popen", lambda cmd, shell=True: calls.append(cmd) or True)
    monkeypatch.setattr(launch_mod, "bring_to_front", lambda hint: True)

    res = launch_mod.launch(ctx, "calc")
    assert res.success
    assert calls == []
    assert "reused" in res.message
