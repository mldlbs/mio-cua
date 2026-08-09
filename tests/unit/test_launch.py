from mio_cua.tools.launch import _normalize_path, _normalize_command, _resolve_command


def test_normalize_path_collapses_double_backslash():
    assert _normalize_path(r"D:\\Users\\gf1913\\Desktop\\smoke_numbers.txt") \
        == r"D:\Users\gf1913\Desktop\smoke_numbers.txt"


def test_normalize_path_keeps_single_backslash():
    assert _normalize_path(r"D:\Users\a\b.txt") == r"D:\Users\a\b.txt"


def test_normalize_path_keeps_unc_prefix():
    # UNC paths (leading double backslash) are left untouched.
    assert _normalize_path(r"\\server\share\f.txt") == r"\\server\share\f.txt"


def test_normalize_command_fixes_file_argument():
    out = _normalize_command(r"notepad D:\\Users\\\\g\\smoke_numbers.txt")
    assert out == r"notepad D:\Users\g\smoke_numbers.txt"


def test_normalize_command_plain_app_unchanged():
    assert _normalize_command("calc") == "calc"


def test_resolve_browser_command_to_full_path():
    # msedge/chrome are not on PATH (they install under Program Files); launch
    # must resolve the command to the known install path or Popen fails.
    out = _resolve_command(r"msedge D:\Users\gf1913\Desktop\vision_test.html")
    assert out.startswith('"C:\\Program Files (x86)\\Microsoft\\Edge')
    assert "msedge.exe" in out
    assert "vision_test.html" in out


def test_resolve_chrome_to_full_path():
    out = _resolve_command("chrome https://example.com")
    assert out.startswith('"C:\\Program Files\\Google\\Chrome')
    assert "chrome.exe" in out


def test_resolve_leaves_non_browser_command_alone():
    assert _resolve_command("notepad") == "notepad"
    assert _resolve_command("calc") == "calc"
