# PyPI Release Guide

How to publish `mio-cua` to PyPI. Requires a PyPI API token (created at
<https://pypi.org/manage/account/token/> with the `mio-cua` project).

## Prerequisites

- `build` and `twine` installed: `pip install build twine`
- A PyPI API token. Either:
  - set `$env:TWINE_USERNAME = "__token__"` and `$env:TWINE_PASSWORD = "<token>"`
  - or create `%USERPROFILE%\.pypirc`:
    ```ini
    [pypi]
    username = __token__
    password = pypi-xxxx
    ```
  - or set `$env:TWINE_PASSWORD` and pass `-u __token__` on the command line.

## Steps

### 1. Bump the version

Edit `pyproject.toml` (`version = "0.2.0"`) and `server.json`
(two `version` fields — top level and the package entry).

### 2. Update the CHANGELOG

Move the `[Unreleased]` notes into a new `[0.2.1]` (or next version) section.
Keep the `[version]: https://github.com/mldlbs/mio-cua/compare/...` links at the
bottom updated.

### 3. Tag and push

```bash
git add pyproject.toml server.json CHANGELOG.md
git commit -m "release: bump to vX.Y.Z"
git push origin master
git tag -a vX.Y.Z -m "vX.Y.Z: <summary>"
git push origin vX.Y.Z
```

### 4. Build clean artifacts

```bash
Remove-Item -Recurse -Force dist, build, *.egg-info -ErrorAction SilentlyContinue
python -m build
python -m twine check dist/*
```

Expected: `Successfully built mio_cua-X.Y.Z.tar.gz and ...whl`, `twine check` → PASSED.

### 5. Upload

```bash
python -m twine upload dist/*
```

Expected output ends with `View at: https://pypi.org/project/mio-cua/`.

### 6. Smoke-test the installed package

In a clean venv (NOT from the repo directory, or Python will import the local
source instead of the wheel):

```bash
python -m venv /tmp/mio_venv
/tmp/mio_venv/Scripts/python -m pip install mio-cua
/tmp/mio_venv/Scripts/python -c "import mio_cua, importlib.metadata; print(importlib.metadata.version('mio-cua'))"
```

## Notes

- Core deps (PyYAML, pywin32, pywinauto, requests, pynput, Pillow, mss,
  psutil) are installed automatically from the wheel's `dependencies`.
- OCR is an **optional extra**: `pip install "mio-cua[vision]"` (rapidocr).
  GPU: `pip install "mio-cua[gpu]"` (onnxruntime-directml).
- The first `gen-scenario --image` call needs the `[vision]` extra; the core
  package works without it.
- `dist/` is gitignored — build artifacts are never committed.
