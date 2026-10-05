# Why accessibility APIs aren't enough for desktop agents

> Draft for dev.to / Medium / HN companion post. Repo: https://github.com/mldlbs/mio-cua

---

I've spent a while trying to get an LLM to operate real desktop software. The
conventional answer is *use the accessibility tree* — UIA on Windows, AT-SPI on Linux,
the DOM in the browser. It's the obvious approach, and it's also where every serious
desktop agent project hits a wall.

Here's the honest list of what I found.

## 1. Accessibility APIs only describe well-behaved apps

UIA (Microsoft's UI Automation) gives you a tree of controls — buttons, text boxes,
tabs — **if the app authors exposed them**. That's true for most modern WinUI / Win32
apps with standard widgets.

But the real world isn't standard:

- **Custom-drawn UIs** (game engines, canvas-based renderers, many line-of-business
  apps) draw pixels and expose almost nothing to UIA.
- **Virtualized lists** report only the visible window, so you can't even enumerate what
  you need to act on.
- **Web content is a black box** — a browser tab's UIA tree is a coarse approximation of
  the page, and it loses the visual structure you need to decide *what to click*.

## 2. Web pages are the biggest gap

A huge share of "automate the office" tasks is *web*: portals, ERPs, admin panels,
internal dashboards. The DOM is right there — so why is it still hard?

- Many sites are SPAs where the DOM changes faster than you can select against it.
- An agent that reads the DOM needs the page rendered in a controlled browser (Puppeteer,
  Playwright) — you've now got a second browser, a session, and a config surface.
- The *visual* layout — where a button is, what's next to it — is exactly what a
  human-based agent should use, and the DOM gives you that only indirectly.

## 3. "Hybrid" frameworks still guess coordinates

You can fuse the accessibility tree with screenshots, then ask the LLM to pick a point
to click. That works — until it doesn't. The model is *guessing* coordinates from a
screenshot. When the window moves, the layout shifts, or two buttons overlap, the guess
is wrong and there's no signal that it was wrong.

## The shift that made it work: perception-validated actions

Instead of "read tree → ask model for a coordinate", mio-cua builds a **scene graph**:

1. OCR + UIA are fused into a single graph where every UI object is a *node* — text,
   type, state, bounding box — plus spatial relations (`leftOf`, `above`, `labelFor`).
2. The perception layer pre-verifies **action candidates**: `click node 7 ('7')
   {'value': '7'} expects {'display': True}`.
3. The LLM never invents coordinates. It **picks from candidates the perception already
   validated**, then the result is checked against the screen again.

And web pages go fully visual too: regions layout analysis + OmniParser turn a screenshot
into buttons/links/inputs — no DOM, no extension, no second browser.

## What this buys you

- **Grounding**: actions come from what the screen actually shows, re-read every step
  ("one action, one perception") — no stale scenes.
- **Verification**: a `Scene Diff` step confirms the screen changed (e.g. calculator
  display `0 → 7`) before moving on.
- **Coverage**: a canvas app, an ancient ERP, and a React portal all reduce to the same
  thing — pixels on a screen.

It's not magic: OCR still struggles with dense tables, and UIA still helps a lot for
accessibility-friendly apps. That's exactly why the fusion (not "vision-only", not
"tree-only") is the interesting design decision.

Verified end-to-end on real Windows 11: notepad, calculator (`123*456=56088`), explorer,
a cross-app workflow (read file → sum in calculator → save result), and web with zero DOM
access — all with a cheap model.

If you're building or evaluating a desktop agent, I'd love to hear where your wall was.
Ours was here: https://github.com/mldlbs/mio-cua
