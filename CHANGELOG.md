# Changelog

All notable changes to mio-cua are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/). `Unreleased` holds in-progress
work; released sections are tagged on `master`.

---

## [Unreleased]

## [0.2.0] - 2026-08-15

### Added

- **Multi-step planner batching** — up to 3 tightly-related actions per plan,
  each re-verified against a fresh lightweight (OCR-only) observation before the
  next runs. Verification failure aborts the whole batch and replans with a
  GUIDANCE hint. Config: `batch_limit` (default 3), `batch_verify` (default True;
  `False` restores one-action-per-observation).
- **High-risk action confirmation** — delete / overwrite / kill_process /
  close_window now require an on-screen Yes/No confirmation before running;
  denial returns `retryable=False` (never retried) and timeout auto-denies
  (fail-closed). Disable with `MIO_CUA_CONFIRM_OFF=1`. Applies to the agent
  tool registry (schema `risk: "high"` + name-based fallback) and the MCP tools
  `mio_kill_process` / `mio_close_window`.
- **Screenshot → YAML scenario** — `mio-cua gen-scenario --image <png> | --capture`
  turns a real desktop screenshot into a YAML scenario (static element list);
  `mio-cua run "task" --simulate-scenario <scene.yaml>` replays it offline through
  the loop with no real input.
- **`mio_cua_GPU=0`** — forces OCR and layout-regions to CPU so onnxruntime /
  DirectML sessions don't run concurrently and spike VRAM.
- Promo assets (`promo/`), blog posts (`blog/`), marketing/growth docs, MIT
  LICENSE, and MCP Registry repository metadata.

### Fixed

- `scene/diff.py` — a curr node matched to a prev node by bbox but with a
  different id was falsely reported as "added" (int-vs-object comparison bug);
  broke scene diff accuracy whenever ids drifted.
- `agent/batch.py` OCR projection now reads observation *elements* (source
  "ocr") instead of scene nodes, so OCR glyphs folded into UIA nodes by
  NodeBuilder are not lost — full vs light frames diff symmetrically.
- `mio-cua run --simulate-scenario` now gives a friendly error on missing or
  malformed scenario YAML instead of a traceback; null element fields are
  tolerated.

## [0.1.5] - 2026-08-15

- MCP server sync to local sub-project repo; MCP Registry metadata.

## [0.1.2] - 2026-08-15

- OCR/vision made an optional extra.

## [0.1.1] - 2026-08-15

- README metadata, `server.json` for the MCP Registry.

[0.2.0]: https://github.com/mldlbs/mio-cua/compare/0.1.5...0.2.0
[0.1.5]: https://github.com/mldlbs/mio-cua/compare/0.1.2...0.1.5
[0.1.2]: https://github.com/mldlbs/mio-cua/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/mldlbs/mio-cua/compare/init...0.1.1
