from mio_cua.automation.windows import set_dpi_aware, get_active_window, get_cursor


def _gnode(type_, bbox=None, semantic="", role=""):
    class _N:
        pass
    n = _N()
    n.type, n.bbox, n.semantic, n.role = type_, bbox, semantic, role
    return n


def test_frame_bbox_prefers_the_window_root():
    """The window control (role='window') IS the frame, even if a larger group
    exists -- identity comes from the control type, not size or text."""
    from mio_cua.automation.windows import frame_bbox
    nodes = [
        _gnode("group", (0, 0, 3000, 3000), semantic="some huge group"),
        _gnode("group", (411, 328, 1920, 1077), role="window"),
    ]
    assert frame_bbox(nodes) == (411, 328, 1920, 1077)


def test_frame_bbox_shell_marker_before_size():
    """Without a window root, the shell marker wins over a larger group."""
    from mio_cua.automation.windows import frame_bbox
    nodes = [
        _gnode("group", (840, 480, 880, 640), semantic="MMUIRenderSubWindowHW"),
        _gnode("group", (0, 0, 3000, 3000), semantic="some other large group"),
    ]
    assert frame_bbox(nodes) == (840, 480, 880, 640)


def test_frame_bbox_defaults_to_the_largest_group():
    """Synthetic scenes without a window root fall back to the largest group."""
    from mio_cua.automation.windows import frame_bbox
    nodes = [
        _gnode("group", (0, 0, 100, 100)),
        _gnode("group", (10, 10, 900, 700)),
        _gnode("group", (419, 328, 1904, 1069)),
        _gnode("text", (0, 0, 5000, 5000), semantic="a huge text node, not a group"),
    ]
    assert frame_bbox(nodes) == (419, 328, 1904, 1069)


def test_frame_bbox_ignores_non_group_nodes():
    from mio_cua.automation.windows import frame_bbox
    assert frame_bbox([_gnode("text", (0, 0, 10, 10))]) is None
    assert frame_bbox(None) is None


def test_dpi_aware_runs():
    set_dpi_aware()  # should not raise


def test_get_cursor_tuple():
    x, y = get_cursor()
    assert isinstance(x, int)
    assert isinstance(y, int)


def test_get_active_window_str():
    title = get_active_window()
    assert isinstance(title, str)


def test_focus_window_empty_title_returns_false():
    from mio_cua.automation.windows import focus_window
    assert focus_window("") is False


def test_focus_window_matches_process_for_known_app(monkeypatch):
    """A browser window's title is the PAGE title, so title matching alone can
    never find it. Edge titled "MIO·HUB — 任务总线" contains no "edge". For a
    recognized app name, focus_window must consult the owning process."""
    from mio_cua.automation import windows

    seen = {"process": [], "title": []}

    def fake_title(kw, exact=False):
        seen["title"].append((kw, exact))
        return []

    def fake_process(names):
        seen["process"].append(names)
        return ["hwnd-mock"]

    monkeypatch.setattr(windows, "_windows_matching_title", fake_title)
    monkeypatch.setattr(windows, "_windows_matching_process", fake_process)
    monkeypatch.setattr(windows, "_focus_latest", lambda hwnds: bool(hwnds))

    assert windows.focus_window("Edge") is True
    assert ("msedge",) in seen["process"], "must match by owning process"
    assert ("Edge", True) in seen["title"], "exact title still tried first"


def test_focus_window_skips_process_match_for_literal_title(monkeypatch):
    """An unrecognized literal title must not enumerate every top-level
    process on the desktop looking for a process named after it."""
    from mio_cua.automation import windows

    seen = {"process": []}

    def fake_title(kw, exact=False):
        # substring step returns a match so the UIA fallback never runs
        return [] if exact else ["hwnd-literal"]

    monkeypatch.setattr(windows, "_windows_matching_title", fake_title)
    monkeypatch.setattr(
        windows, "_windows_matching_process",
        lambda names: seen["process"].append(names) or [])
    monkeypatch.setattr(windows, "_focus_latest", lambda hwnds: bool(hwnds))

    title = "MIO·HUB — 任务总线"  # real Edge window title, not an app name
    assert windows.focus_window(title) is True
    assert seen["process"] == [], "unknown titles must not trigger process scan"


def test_focus_window_unknown_literal_is_fast_and_skips_uia(monkeypatch):
    """FR-3: the old step-5 UIA fallback called Desktop(backend="uia").windows()
    twice, hanging for 180s+ on an unmatchable literal title. Steps 1/4 already
    cover exact and substring matching via win32gui.EnumWindows, so the UIA pass
    must be gone -- a full-desktop enumeration is exactly what we never want."""
    import time

    import pywinauto

    from mio_cua.automation import windows

    def boom(*a, **k):
        raise AssertionError("focus_window must not enumerate the full desktop via UIA")

    monkeypatch.setattr(pywinauto, "Desktop", boom)
    monkeypatch.setattr(windows, "_windows_matching_title", lambda *a, **k: [])
    monkeypatch.setattr(windows, "_windows_matching_process", lambda names: [])
    monkeypatch.setattr(windows, "_focus_latest", lambda hwnds: False)

    start = time.time()
    assert windows.focus_window("definitely-not-a-window-xyz") is False
    assert time.time() - start < 5.0


def test_focus_window_no_match_does_not_touch_uia(monkeypatch):
    from mio_cua.automation import windows

    monkeypatch.setattr(windows, "_windows_matching_title", lambda *a, **k: [])
    monkeypatch.setattr(windows, "_windows_matching_process", lambda names: [])

    assert windows.focus_window("nope") is False


def test_matches_target_uses_process_when_title_hides_app(monkeypatch):
    """Edge's window title is the page title and never contains 'edge'; the
    owning process is the only reliable identity."""
    from mio_cua.automation import windows

    monkeypatch.setattr(windows, "get_active_window",
                        lambda: "MIO·HUB — 任务总线")
    monkeypatch.setattr(windows, "get_active_process", lambda: "msedge")
    assert windows.matches_target("Edge") is True


def test_matches_target_rejects_other_app(monkeypatch):
    from mio_cua.automation import windows

    monkeypatch.setattr(windows, "get_active_window",
                        lambda: "DevTools - localhost:3000")
    monkeypatch.setattr(windows, "get_active_process", lambda: "chrome")
    assert windows.matches_target("Edge") is False


def test_matches_target_localized_title_needs_no_process(monkeypatch):
    from mio_cua.automation import windows

    monkeypatch.setattr(windows, "get_active_window", lambda: "微信")
    monkeypatch.setattr(windows, "get_active_process", lambda: "")  # unreadable
    assert windows.matches_target("wechat") is True


def test_matches_target_stored_title_is_title_only(monkeypatch):
    """A stored title string carries no process info, so it must NOT be
    upgraded to a match just because some process name happens to fit."""
    from mio_cua.automation import windows

    monkeypatch.setattr(windows, "get_active_process", lambda: "msedge")
    assert windows.matches_target("Edge", "MIO·HUB — 任务总线") is False
    assert windows.matches_target("") is False


def _obs(title):
    import time
    from mio_cua.models.observation import Observation
    return Observation(screenshot_path="", timestamp=time.time(),
                       active_window=title, dpi_scale=1.0)


def test_check_context_mismatch_does_not_raise(monkeypatch):
    """Regression: _check_context called get_active_window() without importing
    it, so the FIRST context mismatch killed the whole run with
    "loop error: name 'get_active_window' is not defined" (browser scenario
    died after 1 step)."""
    from mio_cua.agent import loop as loop_mod
    from mio_cua.automation import windows

    focus_calls = []
    monkeypatch.setattr(loop_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(windows, "matches_target", lambda t, w=None, p=None: False)

    loop_obj = loop_mod.AgentLoop.__new__(loop_mod.AgentLoop)
    loop_obj.registry = type("R", (), {
        "call": lambda self, name, params, ctx: focus_calls.append(name)})()
    loop_obj.perception = type("P", (), {})()   # observe() must never be reached
    loop_obj.events = type("E", (), {"publish": lambda self, e: None})()
    loop_obj._make_ctx = lambda obs: None

    task = type("T", (), {"target_context": {"app": "Edge"}})()

    obs_out, ok = loop_obj._check_context(task, _obs("some - Google Chrome"))
    assert ok is False
    assert focus_calls == ["focus_window"] * 5, "must retry focus 5 times"


def test_check_context_already_aligned_skips_focus():
    from mio_cua.agent import loop as loop_mod

    focus_calls = []
    loop_obj = loop_mod.AgentLoop.__new__(loop_mod.AgentLoop)
    loop_obj.registry = type("R", (), {
        "call": lambda self, name, params, ctx: focus_calls.append(name)})()
    loop_obj._make_ctx = lambda obs: None

    task = type("T", (), {"target_context": {"app": "Edge"}})()
    _, ok = loop_obj._check_context(task, _obs("Edge - welcome"))
    assert ok is True
    assert focus_calls == [], "already aligned -> no focus attempt"
