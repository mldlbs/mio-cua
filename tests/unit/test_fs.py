import os

from mio_cua.tools.fs import make_dir, move_file, move_files, list_dir, read_file, write_file, search_files


class Ctx:
    current_action_id = "t"


def test_make_dir_creates(tmp_path):
    target = tmp_path / "a" / "b"
    r = make_dir(Ctx(), path=str(target))
    assert r.success is True
    assert target.is_dir()


def test_make_dir_idempotent(tmp_path):
    target = tmp_path / "a"
    target.mkdir()
    r = make_dir(Ctx(), path=str(target))
    assert r.success is True


def test_move_file_into_dir(tmp_path):
    src = tmp_path / "x.txt"
    src.write_text("hi")
    dest = tmp_path / "docs"  # non-existent dir -> created, file moves inside
    r = move_file(Ctx(), src=str(src), dest=str(dest))
    assert r.success is True
    assert not src.exists()
    assert (dest / "x.txt").read_text() == "hi"


def test_move_file_into_existing_dir(tmp_path):
    src = tmp_path / "x.txt"
    src.write_text("hi")
    dest = tmp_path / "docs"
    dest.mkdir()
    r = move_file(Ctx(), src=str(src), dest=str(dest))
    assert r.success is True
    assert (dest / "x.txt").read_text() == "hi"


def test_move_file_refuses_overwrite(tmp_path):
    src = tmp_path / "x.txt"
    src.write_text("hi")
    dest = tmp_path / "docs"
    dest.mkdir()
    (dest / "x.txt").write_text("keep")
    r = move_file(Ctx(), src=str(src), dest=str(dest))
    assert r.success is False
    assert (dest / "x.txt").read_text() == "keep"
    assert src.exists()


def test_move_file_missing_source(tmp_path):
    r = move_file(Ctx(), src=str(tmp_path / "nope.txt"), dest=str(tmp_path))
    assert r.success is False


def test_list_dir_lists_files_first(tmp_path):
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "zzz").mkdir()
    r = list_dir(Ctx(), path=str(tmp_path))
    assert r.success is True
    lines = r.message.splitlines()
    # directory listed last, files sorted
    assert lines[-1] == "zzz"
    assert lines[0] == "a.txt"


def test_move_files_batch(tmp_path):
    a = tmp_path / "a.txt"; a.write_text("a")
    b = tmp_path / "b.pdf"; b.write_text("b")
    dest = tmp_path / "docs"
    r = move_files(Ctx(), files=[str(a), str(b)], dest=str(dest))
    assert r.success is True
    assert not a.exists() and not b.exists()
    assert (dest / "a.txt").read_text() == "a"
    assert (dest / "b.pdf").read_text() == "b"
    assert "moved 2 files" in r.message


def test_move_files_skips_missing_and_exists(tmp_path):
    a = tmp_path / "a.txt"; a.write_text("a")
    dest = tmp_path / "docs"; dest.mkdir()
    (dest / "a.txt").write_text("keep")
    r = move_files(Ctx(), files=[str(a), str(tmp_path / "nope.txt")], dest=str(dest))
    assert r.success is False  # nothing actually moved
    assert a.exists()  # a.txt not moved (exists in dest)
    assert (dest / "a.txt").read_text() == "keep"  # not overwritten
    assert "SKIP" in r.message


# --- read_file ---

def test_read_file_returns_content(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello world", encoding="utf8")
    r = read_file(Ctx(), path=str(p))
    assert r.success is True
    assert r.message == "hello world"


def test_read_file_truncates_with_notice(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * 5000, encoding="utf8")
    r = read_file(Ctx(), path=str(p), max_chars=100)
    assert r.success is True
    assert r.message.startswith("x" * 100)
    assert "truncated" in r.message
    assert "5000" in r.message


def test_read_file_missing_fails(tmp_path):
    r = read_file(Ctx(), path=str(tmp_path / "nope.txt"))
    assert r.success is False
    assert r.retryable is True


def test_read_file_requires_path():
    r = read_file(Ctx())
    assert r.success is False
    assert r.retryable is True


def test_read_file_binary_fails(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\x00\x01\x02\xff\xfe")
    r = read_file(Ctx(), path=str(p))
    assert r.success is False
    assert r.retryable is True


def test_read_file_clamps_max_chars(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hi", encoding="utf8")
    r = read_file(Ctx(), path=str(p), max_chars=999999)
    assert r.success is True
    assert r.message == "hi"


# --- write_file ---

def test_write_file_create_new(tmp_path):
    p = tmp_path / "new.txt"
    r = write_file(Ctx(), path=str(p), content="hello")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "hello"


def test_write_file_create_refuses_existing(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("keep", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="new")
    assert r.success is False
    assert r.retryable is False
    assert "refusing" in r.message.lower()
    assert p.read_text(encoding="utf8") == "keep"


def test_write_file_append(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("one\n", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="two", mode="append")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "one\ntwo"


def test_write_file_append_creates_missing(tmp_path):
    p = tmp_path / "new.txt"
    r = write_file(Ctx(), path=str(p), content="x", mode="append")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "x"


def test_write_file_write_needs_allow_overwrite(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("keep", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="new", mode="write")
    assert r.success is False
    assert r.retryable is False
    assert "refusing" in r.message.lower()
    assert p.read_text(encoding="utf8") == "keep"


def test_write_file_write_with_allow_overwrite(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("keep", encoding="utf8")
    r = write_file(Ctx(), path=str(p), content="new", mode="write", allow_overwrite=True)
    assert r.success is True
    assert p.read_text(encoding="utf8") == "new"


def test_write_file_creates_parent_dirs(tmp_path):
    p = tmp_path / "x" / "y" / "a.txt"
    r = write_file(Ctx(), path=str(p), content="hi")
    assert r.success is True
    assert p.read_text(encoding="utf8") == "hi"


def test_write_file_invalid_mode(tmp_path):
    p = tmp_path / "a.txt"
    r = write_file(Ctx(), path=str(p), content="x", mode="bogus")
    assert r.success is False
    assert r.retryable is True


def test_write_file_requires_args():
    r = write_file(Ctx(), path="x")
    assert r.success is False
    assert r.retryable is True
    r2 = write_file(Ctx(), content="x")
    assert r2.success is False
    assert r2.retryable is True


# --- search_files ---

def test_search_by_name(tmp_path):
    (tmp_path / "report_2026.txt").write_text("x", encoding="utf8")
    (tmp_path / "other.md").write_text("y", encoding="utf8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "report_backup.txt").write_text("z", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), name="report")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("report_2026.txt" in ln for ln in lines)
    assert any("report_backup.txt" in ln for ln in lines)
    assert not any("other.md" in ln for ln in lines)


def test_search_by_ext(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf8")
    (tmp_path / "b.md").write_text("y", encoding="utf8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.TXT").write_text("z", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), ext="txt")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("a.txt" in ln for ln in lines)
    assert any("c.TXT" in ln for ln in lines)
    assert not any("b.md" in ln for ln in lines)


def test_search_by_content_pattern(tmp_path):
    (tmp_path / "a.txt").write_text("contains the magic word", encoding="utf8")
    (tmp_path / "b.txt").write_text("nothing special", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), pattern="magic")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("a.txt" in ln for ln in lines)
    assert not any("b.txt" in ln for ln in lines)


def test_search_combined_filters(tmp_path):
    (tmp_path / "notes_2026.txt").write_text("project alpha", encoding="utf8")
    (tmp_path / "notes_2026.md").write_text("project alpha", encoding="utf8")
    (tmp_path / "other.txt").write_text("project alpha", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), name="notes", ext="txt", pattern="alpha")
    assert r.success is True
    lines = r.message.splitlines()
    assert any("notes_2026.txt" in ln for ln in lines)
    assert not any("notes_2026.md" in ln for ln in lines)
    assert not any("other.txt" in ln for ln in lines)


def test_search_respects_max_results(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf8")
    r = search_files(Ctx(), path=str(tmp_path), max_results=3)
    assert r.success is True
    lines = r.message.splitlines()
    assert len(lines) == 4  # 3 matches + "... and 7 more"
    assert "7 more" in r.message


def test_search_requires_path():
    r = search_files(Ctx())
    assert r.success is False
    assert r.retryable is True
