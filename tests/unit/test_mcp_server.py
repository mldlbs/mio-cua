import asyncio
import sys

import pytest


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
