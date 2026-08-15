# Building a scene graph: fusing OCR + UIA for grounded action selection

> Draft for dev.to / Medium / HN companion post. Repo: https://github.com/mldlbs/mio-cua

---

A desktop agent that lets the LLM "figure out coordinates from a screenshot" works —
until it doesn't. The window moves, the layout shifts, two buttons overlap, and the
model guesses wrong with no way to notice.

The design we landed on in mio-cua is different: **the perception layer produces a
*scene graph* plus *validated action candidates*, and the LLM only ever picks from
those candidates.** The model never invents a coordinate.

This post is a tour of how that graph is built, why each piece exists, and the failure
modes it kills.

## The pipeline

```
capture (active window)
   → OCR text layer (rapidocr, GPU via DirectML)
   → UIA tree (pywinauto)
   → merge          (dedupe overlaps, stable ids)
   → scene nodes    (type / text / bbox / state)
   → relations      (leftOf, above, labelFor, near, containment)
   → affordances    (click node 7, type into node 3, with expected side-effects)
```

## 1. Merge: OCR and UIA must agree, and ids must be stable

The whole thing hinges on **stable ids**. If the same physical button gets id `4` one
frame and `9` the next, every action resolves against the wrong control.

Two sources are merged with overlap detection:

- **OCR** sees *pixels* — it knows the visible glyph, even for custom-drawn controls
  that expose nothing to UIA.
- **UIA** sees *semantics* — role, state, name — and is stable across minor rendering
  jitter.

Rules that matter:

- If OCR and UIA overlap, keep the **richer** one: UIA text wins when it exists, but
  when OCR sees ASCII text that differs from the UIA localized name (calculator digit
  `7` vs. UIA `一`), the **on-screen glyph wins** — that's what the user (and the LLM's
  screenshot) actually sees.
- Ids are assigned **by screen position**, not scan order, because UIA/OCR enumeration
  order varies between frames. Sort by `(top, left)`; unpositioned boxes go last.
- When a UIA container (a giant editor pane) dwarfs an OCR box by >25×, don't fold the
  text into the container — keep it as its own node.

## 2. Relations: the graph part of "scene graph"

Flat lists of controls are fine for clicking, but tasks like "type into the field next
to *文件名:*" need structure. `RelationBuilder` computes:

- `parent`/`child` — containment (ignored when a child is ~90% of the parent).
- `leftOf` / `above` / `below` — rough spatial ordering from bounding-box centers.
- `near` — adjacency within 120px, used to pair label ↔ control.
- `labelFor` — a short text node left of or above a control is its label.

`labelFor` is the workhorse for **dialogs**, where modern Win11 save dialogs expose
almost nothing via UIA and the field label is only OCR text.

## 3. Affordances: perception validates the action, not the LLM

The critical piece. For every enabled node, rules produce an `Affordance` — a *click* or
*type* candidate:

```python
Affordance(node_id=7, action="click", params={"value": "7"}, expected={"display": True})
```

Key heuristics:

- **Digit / operator buttons** get a `params.value`; operators additionally set
  `expected={"display": "unchanged"}` so the model knows pressing `+` is *not supposed*
  to change the readout and doesn't re-click it.
- **Display inference**: a large, right-aligned, mostly-numeric region (`>150×40px`,
  ≤4 words) is treated as the window's *result display*. Digit buttons below/left of it
  imply `expected.display == True`.
- **Dialog buttons** like `保存(S)` / `OK` / `Cancel` — which Win11 dialogs only surface
  as OCR text — match a known-button dictionary and become clickable.
- **Field labels** (`文件名(N):`) turn the text node to their right into a `type` target,
  using `leftOf`/`near`/`labelFor` relations to find the box without any coordinate
  guessing.

## 4. Verification: Scene Diff closes the loop

An affordance's `expected` field is checked after acting. `Scene Diff` matches nodes
across frames (by id first, then closest bbox center) and reports
`text_changed`/`added`/`removed`/`moved`/`state_changed`. Clicking `7` should change the
display `0 → 7`; if it doesn't, the loop knows the click missed and retries (Recovery
re-focuses the window first).

## Why "one action, one perception"

The most important operational rule: **re-read the screen before every action**. It
sounds wasteful, but with the OCR cache keyed on a perceptual signature (window title +
rect + 24×24 grayscale fingerprint), unchanged windows skip re-inference entirely. A
calculator that hasn't changed reuses the cached text layer; the moment the display
updates, the signature changes and the cache invalidates.

This kills the classic failure: an agent that plans five clicks against one stale scene,
then clicks a button that moved two frames ago.

## What this buys in practice

- **Grounding**: actions come from validated candidates — the LLM cannot hallucinate a
  coordinate.
- **Self-verification**: `expected.display` turns "did my click land?" into a
  checkable diff, not a vibe.
- **Coverage**: custom-drawn UIs, canvas apps, and OCR-only dialogs all reduce to the
  same scene graph.

It's not magic — OCR still struggles with dense tables, and scene-graph heuristics are
tuned for dialog-style layouts. But the architecture is the point: **perception is the
source of truth, the LLM is the decision-maker, and the two never disagree silently.**

All five end-to-end scenarios (notepad, calculator, explorer, cross-app, web-without-DOM)
run on this graph with a cheap model:
https://github.com/mldlbs/mio-cua
