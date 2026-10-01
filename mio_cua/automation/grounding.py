"""Deterministic grounding: turn a model's action intent into a *safe* click.

This is the execution-boundary half of "de-modeling" mio-cua. The Planner may
hand us an ``element_id`` (resolved once during perception) or raw ``x/y``
coords. We must NOT blindly trust either at execution time:

* An ``element_id`` points at a bbox that was correct when the screenshot was
  taken, but the desktop may have moved/occluded/closed it since.
* Raw ``x/y`` from the model may land in the void, on a modal dialog, or on a
  different (non-target) window.

``Grounder.resolve`` re-queries the *live* UIA tree at click time, matches the
intended element, verifies it is visible + enabled + on the target window, and
returns the live center. If the live desktop cannot be read, it degrades
gracefully to the cached reference bbox (the old behaviour) instead of failing
every click.

All win32 / pywinauto imports are lazy (inside methods) so importing this
module never requires a desktop.
"""

import logging
from typing import Any, Callable, List, Optional, Tuple

from mio_cua.models.action import Action
from mio_cua.models.element import Element

logger = logging.getLogger(__name__)


class GroundingError(Exception):
    """Raised when an action cannot be safely grounded on the live desktop.

    ``ambiguous`` marks the case where the target matched multiple live
    elements equally well (e.g. two identical "OK" buttons). Such failures
    should make the planner *replan* (pick a less ambiguous selector) rather
    than blindly retry the same intent.
    """

    def __init__(self, message: str = "", *, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


LiveSource = Callable[[], List[Element]]
RectSource = Callable[[], Tuple[int, int, int, int]]


def _center(bbox) -> Tuple[int, int]:
    left, top, width, height = bbox
    return int(left + width / 2), int(top + height / 2)


def _contains(bbox, x: int, y: int) -> bool:
    left, top, width, height = bbox
    return left <= x <= left + width and top <= y <= top + height


class Grounder:
    def __init__(
        self,
        live_source: Optional[LiveSource] = None,
        window_rect: Optional[RectSource] = None,
    ):
        # Defaults are resolved lazily so this class never imports win32 at
        # construction time.
        self._live_source = live_source
        self._window_rect = window_rect

    # -- live sources (lazy) ------------------------------------------
    def _live(self) -> List[Element]:
        try:
            if self._live_source is not None:
                return self._live_source()
            from mio_cua.automation.uia import get_elements

            return get_elements()
        except Exception:  # pragma: no cover - desktop unreadable
            logger.warning("live UIA read failed; degrading to cached bbox", exc_info=True)
            return []

    def _win_rect(self) -> Optional[Tuple[int, int, int, int]]:
        if self._window_rect is not None:
            return self._window_rect()
        from mio_cua.automation.windows import get_active_window_rect

        try:
            return get_active_window_rect()
        except Exception:
            return None

    # -- matching -----------------------------------------------------
    @staticmethod
    def _match_live(ref: Element, live: List[Element]) -> Optional[Element]:
        """Find the live UIA element that corresponds to a perceived ``ref``.

        Match by (text, role) when the ref has text; otherwise by bbox
        proximity. Among matches pick the one whose center is closest to the
        ref center (handles small drift between frames). When two candidates
        are *equally* close (ambiguous target, e.g. two identical "OK"
        buttons), raise so the planner picks a less ambiguous selector instead
        of us guessing.
        """
        candidates = [e for e in live if getattr(e, "visible", True) and getattr(e, "enabled", True)]
        if not candidates:
            return None
        rcx, rcy = _center(ref.bbox)
        if getattr(ref, "text", ""):
            same = [
                e for e in candidates
                if e.text == ref.text and e.role == ref.role
            ]
            pool = same or candidates
        else:
            pool = candidates
        best: Optional[Element] = None
        best_d = None
        tie_count = 0
        for e in pool:
            lcx, lcy = _center(e.bbox)
            d = (lcx - rcx) ** 2 + (lcy - rcy) ** 2
            if best_d is None or d < best_d:
                best, best_d = e, d
                tie_count = 1
            elif abs(d - best_d) <= 16:  # ~4px tie -> ambiguous
                tie_count += 1
        if best is not None and tie_count > 1 and len({_center(e.bbox) for e in pool}) > 1:
            raise GroundingError(
                f"target {getattr(ref, 'text', '')!r} matches {tie_count} ambiguous "
                f"live elements; cannot safely pick one", ambiguous=True)
        return best

    @staticmethod
    def _hit_test(x: int, y: int, live: List[Element]) -> Optional[Element]:
        """Topmost interactive element at (x, y): smallest-area element whose
        bbox contains the point."""
        hits = [e for e in live if _contains(e.bbox, x, y)]
        if not hits:
            return None
        return min(hits, key=lambda e: e.bbox[2] * e.bbox[3])

    # -- public -------------------------------------------------------
    def resolve(self, action: Action, reference_obs: Any) -> Optional[Tuple[int, int]]:
        """Return safe (x, y) for the action, or ``None`` if nothing to ground
        (e.g. a ``key`` action with no coordinates).

        Raises ``GroundingError`` when the action targets a specific element /
        point that cannot be safely placed on the live target window.
        """
        element_id = action.params.get("element_id")
        if element_id is not None:
            return self._resolve_element(element_id, reference_obs)
        x, y = action.params.get("x"), action.params.get("y")
        if x is None or y is None:
            return None  # no spatial target -- nothing to ground
        return self._resolve_coords(int(x), int(y))

    def _resolve_element(self, element_id, reference_obs) -> Tuple[int, int]:
        ref = None
        for e in getattr(reference_obs, "elements", []) or []:
            if e.id == element_id or str(e.id) == str(element_id):
                ref = e
                break
        if ref is None:
            raise GroundingError(
                f"element_id {element_id!r} not found in reference observation"
            )
        live = self._live()
        if not live:
            # Live desktop unreadable -- degrade to cached coords (old behaviour)
            # rather than failing every click.
            return _center(ref.bbox)
        matched = self._match_live(ref, live)
        if matched is None or not (matched.visible and matched.enabled):
            raise GroundingError(
                f"target element {ref.text!r} is not visible/enabled on the live desktop"
            )
        cx, cy = _center(matched.bbox)
        rect = self._win_rect()
        if rect is not None and not _contains(rect, cx, cy):
            raise GroundingError(
                f"target element {ref.text!r} falls outside the active window (occluded?)"
            )
        return cx, cy

    def _resolve_coords(self, x: int, y: int) -> Tuple[int, int]:
        live = self._live()
        rect = self._win_rect()
        if rect is not None and not _contains(rect, x, y):
            raise GroundingError(f"click at ({x}, {y}) is outside the active window")
        if live:
            top = self._hit_test(x, y, live)
            if top is None:
                raise GroundingError(
                    f"click at ({x}, {y}) hits no interactive element"
                )
        return x, y
