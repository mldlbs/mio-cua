# mio-cua as an MCP server: giving Claude/Cursor hands on Windows

> Draft for dev.to / Medium / HN. Repo: https://github.com/mldlbs/mio-cua

---

Most of what I write about mio-cua is the computer-use agent: an LLM that sees a
Windows screen and operates it. But the same capabilities ship in a second, arguably
more immediately useful form — **an MCP server**. Any MCP-capable client (Claude,
Cursor, ChatGPT desktop, and a growing list) can grab a copy and start controlling your
desktop today.

## Why MCP for desktop control

Model Context Protocol gives every client one way to discover and call tools. mio-cua's
hard-won desktop capabilities — stable element ids, safe file moves, window management,
keyboard input — become tools any assistant can invoke.

Concretely, the server exposes what the agent already proved in its five end-to-end
scenarios, but as **direct, tool-callable primitives** instead of an open-ended loop:

```
filesystem : list_dir / make_dir / move_file / move_files
windows    : launch / focus_window / get_active_window / list_windows / close_window
input      : click / type / key / drag / scroll / move_mouse / get_cursor
perception : observe_scene / analyze_page / ocr_text / screenshot
utility    : vdesk / clipboard_get / clipboard_set / notify / list_processes /
             kill_process / get_screen_info / sleep
```

That's the "27 tools" figure. The full reference is in [MCP.md](../MCP.md).

## Setup is one JSON block

```json
{ "mcpServers": { "mio-cua": { "command": "mio-cua-mcp", "args": [] } } }
```

Drop that into your client's MCP config (`~/.cursor/mcp.json`, a project `.mcp.json`
for Claude Code, or the ChatGPT desktop MCP settings), and the tools appear. Then you
can ask things like:

- *"整理桌面上散落的文件，按类型归档"*
- *"把 Downloads 里所有截图移到 Pictures"*
- *"打开这个 URL 并截个图"*

No agent loop, no YAML scenario — just tools your assistant already knows how to call.

## What makes these tools safe enough to expose

The "boring 50%" shows up here too:

- **File moves refuse to overwrite** — `mio_move_file`/`mio_move_files` fail
  deterministically instead of clobbering a same-named target.
- **Perceptual grounding is optional but available** — `mio_observe_scene` returns the
  scene graph (elements with stable ids + bounding boxes + verified click/type
  candidates), so a client can act on what perception *validated*, not guessed coordinates.
- **Pure-vision web** — `mio_analyze_page` parses a page screenshot into interactive
  elements (OmniParser) with zero DOM/extension access, so assistants can operate web
  UIs on machines where no browser automation stack is installed.
- **Virtual-desktop isolation** — `mio_vdesk` manages a separate desktop, letting
  clients test on a desktop that doesn't touch your working one.

## Latency is handled in the background

OmniParser's model is ~2GB and takes 10–20s to cold-load. The server **prewarms it on a
low-priority daemon thread** at startup, so the first `mio_analyze_page` call doesn't
block on model load. (`MIO_CUA_NO_PREWARM=1` disables it; the tools still lazy-load if
you'd rather not spend the RAM.)

## Two models of desktop automation in one project

This is the part I like: the same codebase supports **both** paradigms.

- **Agent mode** — say a task in natural language; the loop perceives, plans, acts,
  verifies, recovers. Good for open-ended multi-step work.
- **MCP mode** — expose deterministic primitives; your existing assistant (Claude,
  Cursor, ChatGPT) drives them. Good for "I know exactly what I want done" and for
  keeping control in the client you already live in.

If you've been wanting to hand Claude or Cursor real desktop hands, or you're curious
about a computer-use agent that also speaks MCP:
https://github.com/mldlbs/mio-cua
