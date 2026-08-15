# Pure-vision web automation: no DOM, no extensions

> Draft for dev.to / Medium / HN companion post. Repo: https://github.com/mldlbs/mio-cua

---

"Automate the browser" has a canonical answer: Playwright, Puppeteer, CDP, selectors.
It's powerful — and it's also a separate universe from desktop automation, with its own
config surface, its own session management, and its own failure modes (a selector that
silently matches nothing after a deploy).

mio-cua takes a deliberately different path for web: **the browser tab is just another
window, and we understand it the same way a human does — by looking at it.**

## The stack

For any browser window (Chrome / Edge / Firefox / Brave / Opera / Vivaldi), two extra
visual pipelines run alongside the normal OCR+UIA merge:

1. **Regions layout analysis** (`rapid_layout`, optional) — a document-layout model
   (pp_layout_cdla / publaynet on ONNXRuntime + DirectML) splits the page into coarse
   zones: title, text, table, figure, header, footer, list. The agent gets *page
   structure* without touching the DOM.

2. **OmniParser control detection** (`mio_cua/scene/omniparser.py`, optional) — Microsoft
   OmniParser turns the page *screenshot* into structured elements:
   - `text` nodes: headings and plain text (`interactivity=False`)
   - `icon` nodes: buttons, links, input boxes (`interactivity=True`) with a semantic
     description from a Florence-2 caption model.

These become ordinary scene nodes with ids above the element range, so the existing
click/type machinery just works.

## What this gives you

- **Zero DOM access** — no page source, no extension, no plugin. The agent reads pixels,
  the same way it reads any desktop app.
- **One code path for desktop and web** — a portal, an ERP, and a legacy Win32 app are
  all just "a window to perceive." No dual-world model, no Selenium-vs-UIA schism.
- **Robust to SPA churn** — the page re-rendered? We re-read the screen. There's no
  selector to go stale.

## The cost (honest section)

OmniParser is heavy: torch + transformers + ultralytics, ~2GB of models. So:

- It's **optional and lazy-loaded**. If the weights aren't found, `parse()` returns `[]`
  and the scene simply has no web nodes — the agent still works, just without the
  high-quality web controls.
- **Torch thread caps** (`torch.set_num_threads(2)`) keep the cold-start model load from
  spinning every core to 100% for 10–25s and freezing the machine.
- **Offline-first**: `HF_HUB_OFFLINE=1` so the first parse doesn't stall on an
  unreachable HF CDN.
- **Caching via content signature** — same perceptual fingerprint that caches OCR. An
  unchanged page skips the model entirely; the moment content scrolls or updates, the
  signature changes and both layers invalidate together. First frame ~20s load, then
  ~0.3s/frame.

## The "everywhere" switch

It turns out OmniParser also understands *plain desktop UIs*, not just web pages:
buttons and inputs in Electron apps, tool windows, and dialogs benefit too. So control
detection runs for **any** window by default (`MIO_CUA_WEB_EVERYWHERE=1`); set it to `0`
to go back to browser-title-only gating.

## Verified

The web scenario runs on this stack end-to-end on a real Windows 11 desktop: Edge opens
a local HTML page, the agent clicks a button and types into a field **purely visually**,
then confirms the result on screen — no DOM, no extension, no page source. It PASSed
together with the four desktop scenarios using a cheap model (deepseek-v4-flash).

## When to choose this over Playwright

- You need **one agent that does desktop + web** and don't want two automation worlds.
- The site has no clean selectors, or is canvas-based / heavily custom-rendered.
- You want the agent to behave like a human on the page (what a user sees is what the
  agent sees) — including page structure.

When *not*: heavy, DOM-driven, text-extraction workflows at scale are still better served
by a real browser automation tool. This is a human-mimicking operator, not a scraping
engine.

If you've hit the "selectors broke again" wall, or want to see desktop and web collapse
into one perception pipeline, the repo is here:
https://github.com/mldlbs/mio-cua
