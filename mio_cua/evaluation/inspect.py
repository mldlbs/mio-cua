"""Read-only inspection of recorded Phase 3 traces (backs ``mio-cua history``).

This module only *describes* what is already on disk:

- it never re-executes anything (that is :mod:`mio_cua.evaluation.replay`);
- it never aggregates cross-trace metrics (that is :mod:`mio_cua.evaluation.benchmark`);
- it never touches the desktop, the LLM, or any input device.

Keeping the formatting here (instead of inside ``cli.py``) means the same
rendering can be reused by the MCP ``mio_report`` wrapper or a future web
panel without importing argparse.
"""

import datetime as _dt
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mio_cua.evaluation.schema import Trace

DEFAULT_LIMIT = 20

# ``steps`` is ``None`` when only ``metadata.json`` was read (cheap listing);
# it becomes the real event count once the full trace (or its event log) is loaded.


@dataclass
class TraceSummary:
    """A trace reduced to what ``mio-cua history`` needs to show."""

    path: str
    task_id: str
    goal: str = ""
    status: str = "UNKNOWN"
    started_at: str = ""
    finished_at: str = ""
    duration_s: Optional[float] = None
    steps: Optional[int] = None
    event_counts: Dict[str, int] = field(default_factory=dict)
    failure_category: str = ""
    failure_reason: str = ""
    failure_confidence: float = 0.0
    result_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "steps": self.steps,
            "event_counts": dict(self.event_counts),
            "failure": (
                {
                    "category": self.failure_category,
                    "reason": self.failure_reason,
                    "confidence": self.failure_confidence,
                }
                if self.failure_category
                else None
            ),
            "result_summary": self.result_summary,
        }


# -- parsing helpers ---------------------------------------------------------

def _parse_iso(value: Any) -> Optional[_dt.datetime]:
    if not value:
        return None
    if isinstance(value, _dt.datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_naive_utc(moment: Optional[_dt.datetime]) -> Optional[_dt.datetime]:
    if moment is None:
        return None
    if moment.tzinfo is not None:
        return moment.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return moment


def _duration(started: Any, finished: Any) -> Optional[float]:
    a, b = _as_naive_utc(_parse_iso(started)), _as_naive_utc(_parse_iso(finished))
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds())


def _iso_str(value: Any) -> str:
    """Render a timestamp as ISO-8601; ``str(datetime)`` uses a space separator."""
    if not value:
        return ""
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    return str(value)


def _status_of(trace: Trace) -> str:
    try:
        if trace.success:
            return "SUCCESS"
    except Exception:  # pragma: no cover - defensive: a malformed trace must not break listing
        pass
    if trace.result and str(trace.result.get("status", "")).strip():
        return str(trace.result["status"]).upper()
    return "FAILURE" if trace.failure else "UNKNOWN"


def _event_counts(trace: Trace) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for event in trace.events:
        key = event.event_type or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


# -- building summaries ------------------------------------------------------

def summarize(trace: Trace, path: str = "") -> TraceSummary:
    """Reduce a fully-loaded :class:`Trace` to a :class:`TraceSummary`."""
    failure = trace.failure
    summary = TraceSummary(
        path=path,
        task_id=trace.task_id or trace.trace_id,
        goal=trace.goal or "",
        status=_status_of(trace),
        started_at=_iso_str(trace.started_at),
        finished_at=_iso_str(trace.finished_at),
        duration_s=_duration(trace.started_at, trace.finished_at),
        steps=len(trace.events),
        event_counts=_event_counts(trace),
        failure_category=getattr(failure, "category", "") or "",
        failure_reason=getattr(failure, "reason", "") or "",
        failure_confidence=float(getattr(failure, "confidence", 0.0) or 0.0),
        result_summary=str((trace.result or {}).get("summary", "") or ""),
    )
    return summary


def summarize_dir(path: str) -> TraceSummary:
    """Summarise a trace directory **without** parsing its event log.

    Listing must stay cheap: a real recorded run can have a multi-megabyte
    ``trace.jsonl``, so only ``metadata.json`` is read here. ``steps`` stays
    ``None`` until :func:`summarize` loads the full trace.
    """
    import json

    with open(os.path.join(path, "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)
    events_dropped = {k: v for k, v in meta.items() if k != "events"}
    trace = Trace.from_dict(events_dropped)
    summary = summarize(trace, path=path)
    summary.steps = None
    return summary


def _sort_key(summary: TraceSummary):
    moment = _as_naive_utc(_parse_iso(summary.started_at))
    if moment is None:
        try:
            mtime = os.path.getmtime(summary.path)
            moment = _dt.datetime.fromtimestamp(mtime, _dt.timezone.utc).replace(tzinfo=None)
        except OSError:
            moment = _dt.datetime.min
    return moment


def load_summaries(
    trace_dir: str,
    limit: Optional[int] = DEFAULT_LIMIT,
    failed_only: bool = False,
) -> List[TraceSummary]:
    """List trace summaries under ``trace_dir``, newest first.

    A corrupt/unreadable trace directory is skipped instead of failing the
    whole listing: one bad recording must not hide the other 99.
    """
    if not os.path.isdir(trace_dir):
        return []
    found: List[TraceSummary] = []
    for entry in os.scandir(trace_dir):
        if not entry.is_dir():
            continue
        for root, _dirs, files in os.walk(entry.path):
            if "metadata.json" not in files:
                continue
            try:
                found.append(summarize_dir(root))
            except Exception:
                continue
    found.sort(key=_sort_key, reverse=True)
    if failed_only:
        found = [s for s in found if s.status != "SUCCESS"]
    if limit is not None and limit >= 0:
        found = found[:limit]
    return found


# -- rendering ---------------------------------------------------------------

def _short_goal(goal: str, width: int = 40) -> str:
    text = " ".join((goal or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m{rest:04.1f}s"


def format_table(summaries: List[TraceSummary]) -> str:
    """Render the list view as an aligned table (no trailing whitespace)."""
    if not summaries:
        return ""
    rows = [
        [
            (s.started_at or "")[:10] or "-",
            s.task_id or "-",
            s.status or "UNKNOWN",
            _fmt_duration(s.duration_s),
            _short_goal(s.goal),
        ]
        for s in summaries
    ]
    header = ["DATE", "TASK_ID", "STATUS", "DURATION", "GOAL"]
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render(cells):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()

    lines = [render(header)]
    for row in rows:
        lines.append(render(row))
    return "\n".join(lines)


def _format_counts(counts: Dict[str, int]) -> str:
    if not counts:
        return "-"
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


def format_detail(summary: TraceSummary, events: Optional[List[Any]] = None,
                  include_events: bool = False) -> str:
    """Render the single-trace view; ``include_events`` appends a timeline."""
    lines = [
        f"task {summary.task_id or '-'}   {summary.status}   "
        f"{_fmt_duration(summary.duration_s)}   steps {summary.steps if summary.steps is not None else '-'}",
        f"  goal      : {summary.goal or '-'}",
        f"  started   : {summary.started_at or '-'}",
        f"  finished  : {summary.finished_at or '-'}",
    ]
    if summary.event_counts:
        lines.append(f"  events    : {_format_counts(summary.event_counts)}")
    if summary.failure_category:
        lines.append(
            f"  failure   : {summary.failure_category} "
            f"(confidence {summary.failure_confidence:.2f}) — {summary.failure_reason or '-'}"
        )
    if summary.result_summary:
        lines.append(f"  result    : {summary.result_summary}")
    lines.append(f"  trace     : {summary.path or '-'}")

    if include_events and events:
        lines.append("")
        lines.append("  #   time      event              detail")
        for i, event in enumerate(events, 1):
            stamp = _iso_str(getattr(event, "timestamp", "") or "")
            clock = stamp[11:19] if len(stamp) >= 19 else stamp
            payload = getattr(event, "payload", None) or {}
            detail = _payload_hint(payload)
            lines.append(
                f"  {i:<3} {clock:<9} {str(getattr(event, 'event_type', '?')):<18} {detail}".rstrip()
            )
    return "\n".join(lines)


#: Nested payload blocks worth surfacing first, with the keys that read best.
_HINT_BLOCKS = {
    "observation": ("active_window", "window_title", "element_count", "summary"),
    "plan": ("action_type", "target", "intent"),
    "action": ("tool", "action_type"),
    "belief": ("current_state", "goal"),
    "verification": ("changed", "success", "reason"),
    "progress": ("stance", "summary"),
    "recovery": ("action", "reason"),
}


def _payload_hint(payload: Dict[str, Any]) -> str:
    """One short human line for a timeline row, preferring the useful keys."""
    if not payload:
        return ""
    for block, keys in _HINT_BLOCKS.items():
        nested = payload.get(block)
        if not isinstance(nested, dict):
            continue
        parts = [f"{k}={nested[k]}" for k in keys if nested.get(k) not in (None, "", [], {})]
        params = nested.get("parameters")
        if isinstance(params, dict):
            parts += [f"{k}={v}" for k, v in list(params.items())[:3]]
        if parts:
            return _short_goal(f"{block}: " + " ".join(parts), 60)
    for key in ("action_type", "type", "reason", "status", "message", "text", "summary", "goal"):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return _short_goal(str(value), 60)
    flat = ", ".join(f"{k}={v}" for k, v in list(payload.items())[:3] if v not in (None, "", [], {}))
    return _short_goal(flat, 60)
