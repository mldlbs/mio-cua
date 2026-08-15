import asyncio
import sys

import pytest
from mio_cua.mcp_server import mcp


def _run(coro):
    return asyncio.run(coro)


def test_mcp_lists_expected_tools():
    from mio_cua.mcp_server import mcp
    names = _run(mcp.list_tools())
    tool_names = {t.name for t in names}
    assert "mio_list_dir" in tool_names
    assert "mio_move_files" in tool_names
    assert "mio_launch" in tool_names
    assert "mio_key" in tool_names
    assert "mio_observe_scene" in tool_names
    assert "mio_screenshot" in tool_names
    assert "mio_ocr_text" in tool_names
    assert "mio_analyze_page" in tool_names
    assert "mio_vdesk" in tool_names


def test_mcp_list_dir(tmp_path):
    from mio_cua.mcp_server import mcp
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "zzz").mkdir()
    content, _ = _run(mcp.call_tool("mio_list_dir", {"path": str(tmp_path)}))
    text = content[0].text
    assert "a.txt" in text
    assert "zzz" in text


def test_mcp_make_dir_and_move(tmp_path):
    from mio_cua.mcp_server import mcp
    src = tmp_path / "x.txt"
    src.write_text("hi")
    dest = tmp_path / "docs"
    c1, _ = _run(mcp.call_tool("mio_make_dir", {"path": str(dest)}))
    assert "created" in c1[0].text.lower() or dest.is_dir()
    c2, _ = _run(mcp.call_tool("mio_move_file", {"src": str(src), "dest": str(dest)}))
    assert not src.exists()
    assert (dest / "x.txt").read_text() == "hi"


def test_mcp_move_files_batch(tmp_path):
    from mio_cua.mcp_server import mcp
    a = tmp_path / "a.pdf"; a.write_text("a")
    b = tmp_path / "b.pdf"; b.write_text("b")
    dest = tmp_path / "out"
    content, _ = _run(mcp.call_tool(
        "mio_move_files", {"files": [str(a), str(b)], "dest": str(dest)}))
    assert not a.exists() and not b.exists()
    assert (dest / "a.pdf").read_text() == "a"
    assert (dest / "b.pdf").read_text() == "b"
    assert "moved 2 files" in content[0].text


def test_mcp_missing_path_errors(tmp_path):
    from mio_cua.mcp_server import mcp
    content, _ = _run(mcp.call_tool("mio_list_dir", {"path": str(tmp_path / "nope")}))
    assert "Error" in content[0].text


def test_mcp_observe_scene_returns_window_and_elements():
    from mio_cua.mcp_server import mcp
    content, _ = _run(mcp.call_tool("mio_observe_scene", {"max_elements": 5}))
    text = content[0].text
    assert "Active window" in text
    # either has elements or reports none gracefully
    assert ("id=" in text) or ("no elements" in text)


def test_mcp_screenshot_returns_path(tmp_path):
    from mio_cua.mcp_server import mcp
    out = tmp_path / "shot.png"
    content, _ = _run(mcp.call_tool("mio_screenshot", {"path": str(out)}))
    text = content[0].text
    assert "saved screenshot" in text
    assert out.exists()


def test_mcp_observe_scene_reports_source_and_confidence():
    from mio_cua.mcp_server import mcp
    content, _ = _run(mcp.call_tool("mio_observe_scene", {"max_elements": 3}))
    text = content[0].text
    # the enhanced output should either show src=/conf= or degrade gracefully
    if "id=" in text:
        assert "src=" in text


def test_mcp_analyze_page_graceful_without_omniparser(tmp_path):
    """analyze_page must not crash when OmniParser is unavailable; it should
    return a helpful message. Force-unset the env and clear the cached parser
    so the heavy model is NEVER loaded during this unit test (CPU-only runs
    would otherwise peg the machine)."""
    import os
    from mio_cua.mcp_server import mcp
    from mio_cua.scene import omniparser
    os.environ["OMNIPARSER_DIR"] = str(tmp_path / "no_such_weights")
    omniparser._parser = None  # drop cached (already-loaded) parser
    content, _ = _run(mcp.call_tool("mio_analyze_page", {"max_elements": 3}))
    text = content[0].text
    # parser is None -> tool must never block on model load; it either reports
    # the cold-load hint or degrades gracefully.
    assert ("still loading" in text) or ("no interactive" in text) or ("Error" in text)


def test_mcp_vdesk_uses_script_module():
    """mio_vdesk must locate scripts/vdesk.py (needs to exist for import)"""
    import importlib.util
    import os
    from mio_cua import mcp_server
    v_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(mcp_server.__file__))), "scripts", "vdesk.py")
    assert os.path.isfile(v_path)
    spec = importlib.util.spec_from_file_location("_mio_vdesk_check", v_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(getattr(mod, "ensure_test_desktop", None))
    assert callable(mod.close_desktop)


class _FakeMCPConfirm:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def confirm(self, name, params):
        self.calls.append((name, params))
        return self.answer


def test_mcp_kill_process_rejected_before_running(monkeypatch):
    from mio_cua import mcp_server
    from mio_cua.mcp_server import mcp

    monkeypatch.setattr(mcp_server, "CONFIRMATION", _FakeMCPConfirm(False))
    content, _ = _run(mcp.call_tool(
        "mio_kill_process", {"name": "notepad.exe", "pid": 0, "force": False}))
    text = content[0].text
    assert "Rejected by user: mio_kill_process" in text


def test_mcp_kill_process_approved_runs(monkeypatch):
    from mio_cua import mcp_server
    from mio_cua.mcp_server import mcp

    monkeypatch.setattr(mcp_server, "CONFIRMATION", _FakeMCPConfirm(True))
    content, _ = _run(mcp.call_tool(
        "mio_kill_process", {"name": "no_such_proc_xyz", "pid": 0, "force": False}))
    text = content[0].text
    assert "Error" in text or "killed" in text  # confirm passed -> tool ran


def test_mcp_close_window_requires_confirm(monkeypatch):
    from mio_cua import mcp_server
    from mio_cua.mcp_server import mcp

    fake = _FakeMCPConfirm(False)
    monkeypatch.setattr(mcp_server, "CONFIRMATION", fake)
    content, _ = _run(mcp.call_tool("mio_close_window", {"title": "anything"}))
    text = content[0].text
    assert "Rejected by user: mio_close_window" in text
    assert fake.calls, "close_window must be confirmed"


def test_mcp_low_risk_skips_confirmation(monkeypatch):
    from mio_cua import mcp_server
    from mio_cua.mcp_server import mcp

    fake = _FakeMCPConfirm(False)  # would deny, but must never be asked
    monkeypatch.setattr(mcp_server, "CONFIRMATION", fake)
    content, _ = _run(mcp.call_tool("mio_list_dir", {"path": "."}))
    assert fake.calls == []
