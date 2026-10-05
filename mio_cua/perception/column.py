"""Read an ordered text column out of a flat perception node list.

Chat transcripts, log panes, comment threads and message lists are all the same
shape for us: a scrolling vertical column of text bubbles where we need "the
block that came after the last thing WE said". The multi-turn ChatGPT/DeepSeek
recorder learned this the hard way over three live runs, and the lessons are
structural rather than site-specific, so they live here as pure functions any
scenario can reuse:

  * the anchor is the object WE produced, matched by identity, not by wording;
    a reply that echoes the same identity token must not steal it, so a tall
    reply container (whole answer in one node) can be told from the short bubble
    rows we sent;
  * the node list order is NOT visual order -- a trailing control can be listed
    before the lines above it, so the reader sorts by (y, x) instead of trusting
    the order it was handed, and noise is skipped rather than used as a break;
  * the same text is often exposed twice (a tall container AND its lines, or a
    button row AND its text child), so spans are deduped -- except an exact
    identity token, which must always survive because callers check for it;
  * a boundary marker (the previous turn's trailing token) can open the band
    when our own anchor itself has scrolled out of view.

No site, app or window knowledge is encoded here: the caller passes the tokens,
the noise predicate and the prompt, and gets back ordered text pieces.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

# (y, x, text, bottom) for one collected line; bottom = y + height.
Piece = Tuple[int, int, str, int]

_ROW_MAX_H = 60  # bubble rows are short; whole-answer containers are taller


@dataclass
class ColumnRead:
    """Result of reading one view of a text column."""

    pieces: List[Piece] = field(default_factory=list)
    anchored: bool = False   # our own object was visible -> this view holds the head
    boundary_y: int = 0      # where the band opened (anchor or fallback top)
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(p[2] for p in self.pieces)


def _norm(text: str) -> str:
    return "".join((text or "").split())


def find_band(
    nodes: Sequence,
    tokens: Sequence[str],
    *,
    stop_token: Optional[str] = None,
    top_min: int = 200,
    is_identity: Callable[[str, str], bool],
    in_band: Callable[[tuple], bool],
    row_max_h: int = _ROW_MAX_H,
) -> Tuple[Optional[int], bool, int]:
    """Locate where this column read should start.

    ``nodes`` is a sequence of ``(type, text, bbox)`` (see ``node_tuples``).

    Returns ``(boundary_y, anchored, top)``:
      * ``boundary_y`` -- read everything strictly below this y
      * ``anchored`` -- our own object was found (this view holds the head)
      * ``top`` -- the y the fallback opened at, for diagnostics

    The first pass looks for OUR object by ``is_identity``. Short rows win over
    tall ones when several match, because a reply can begin with the same token
    and its container would otherwise move the anchor onto the answer.
    """
    own_y = None
    own_y_any = None
    for ntype, text, bbox in nodes:
        if ntype == "group" or not bbox or len(bbox) < 4:
            continue
        if not in_band(bbox):
            continue
        if not any(is_identity(text, t) for t in tokens):
            continue
        y = bbox[1]
        own_y_any = y if own_y_any is None else max(own_y_any, y)
        if bbox[3] < row_max_h:
            own_y = y if own_y is None else max(own_y, y)
    if own_y is None:
        own_y = own_y_any
    if own_y is not None:
        return own_y, True, own_y

    # Fallback: our object is gone (scrolled out). Open the band on the previous
    # turn's marker so this turn's block is the only content after it.
    top = top_min
    if stop_token:
        for ntype, text, bbox in nodes:
            if ntype == "group" or not bbox or len(bbox) < 4:
                continue
            if not in_band(bbox):
                continue
            stripped = (text or "").strip()
            if stripped == stop_token or (
                bbox[3] < row_max_h and is_identity(text, stop_token)
            ):
                top = max(top, bbox[1])
    return top, False, top


def collect_pieces(
    nodes: Sequence,
    boundary_y: int,
    *,
    in_band: Callable[[tuple], bool],
    is_noise: Callable[[str], bool],
    tokens: Sequence[str],
    prompt: Optional[str] = None,
    floor: Optional[int] = None,
    badge_below_floor: bool = True,
    row_max_h: int = _ROW_MAX_H,
) -> List[Piece]:
    """Ordered, deduped, boundary-cut text pieces below ``boundary_y``.

    Noise is dropped in place (never a break); the exact identity token is kept
    even below the floor and through dedup; a node that is a verbatim slice of
    ``prompt`` is our own echoed message, not content.

    ``in_band`` must bound the column horizontally and above (browser chrome);
    the floor is applied HERE rather than in ``in_band`` so the token badge can
    be excepted -- a DOM input box can overlap the last row and put the badge
    below the detected floor.
    """
    norm_prompt = _norm(prompt or "")
    raw: List[Piece] = []
    for ntype, text, bbox in nodes:
        if ntype == "group":
            continue
        text = (text or "").strip()
        if not text or not bbox or len(bbox) < 4:
            continue
        squashed = _norm(text)
        x, y = bbox[0], bbox[1]
        if not in_band(bbox):
            continue
        if y <= boundary_y:
            continue
        is_badge = text in tokens
        if floor is not None and y >= floor and not (is_badge and badge_below_floor):
            continue
        if is_noise(text):
            continue
        if norm_prompt and len(squashed) >= 6 and squashed in norm_prompt:
            continue
        raw.append((y, x, text, y + bbox[3]))

    raw.sort()

    # Drop a line that merely re-renders an already-kept one: the same span
    # (a tall container covering its lines) or the same text within a kept
    # row's span (a button row plus its text child). The exact token badge is
    # always kept -- it is identity, and dropping it breaks tagging.
    kept: List[Piece] = []
    for y, x, text, bottom in raw:
        duplicate = any(
            k[3] >= y and ((k[3] - k[0]) >= row_max_h or _norm(k[2]) == _norm(text))
            for k in kept
        )
        if duplicate and text not in tokens:
            continue
        kept.append((y, x, text, bottom))

    # Boundary: our trailing token ends the block; anything below it belongs to
    # the next turn (post-hoc reads) or to action rows.
    badge_idx = [i for i, p in enumerate(kept) if p[2] in tokens]
    if badge_idx and badge_idx[-1] > 0:
        kept = kept[: badge_idx[-1] + 1]
    return kept


def stitch_lines(acc: Sequence[str], lines: Sequence[str]) -> List[str]:
    """Prepend the non-overlapping head of ``lines`` to ``acc``.

    Views from consecutive scroll-ups overlap by a few lines. The overlap is the
    longest run where the accumulated head equals the new view's tail; matching
    normalizes whitespace because OCR of one line can differ between positions.
    No overlap -> the new view sits entirely above and is prepended whole.
    """
    if not acc:
        return list(lines)
    a = [_norm(x) for x in acc]
    b = [_norm(x) for x in lines]
    for k in range(min(len(a), len(b)), 0, -1):
        if a[:k] == b[-k:]:
            return list(lines[:-k]) + list(acc)
    return list(lines) + list(acc)


def read_column(
    nodes: Sequence,
    *,
    tokens: Sequence[str],
    in_band: Callable[[tuple], bool],
    is_identity: Callable[[str, str], bool],
    is_noise: Callable[[str], bool],
    stop_token: Optional[str] = None,
    prompt: Optional[str] = None,
    floor: Optional[int] = None,
    top_min: int = 200,
    row_max_h: int = _ROW_MAX_H,
) -> ColumnRead:
    """The whole read for one view: find the band, then collect its pieces."""
    boundary_y, anchored, top = find_band(
        nodes, tokens, stop_token=stop_token, top_min=top_min,
        is_identity=is_identity, in_band=in_band, row_max_h=row_max_h,
    )
    pieces = collect_pieces(
        nodes, boundary_y, in_band=in_band, is_noise=is_noise, tokens=tokens,
        prompt=prompt, floor=floor, row_max_h=row_max_h,
    )
    meta = {"boundary_y": boundary_y, "fallback_top": top}
    return ColumnRead(pieces=pieces, anchored=anchored, boundary_y=boundary_y, meta=meta)
