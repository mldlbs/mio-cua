import os

from mio_cua.tools.fs import make_dir, move_file, move_files, list_dir


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
