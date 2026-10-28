"""Normalise V1 and V2 run records into ONE stats schema.

V2 emits structured events through its sink; V1 has no such bus. We must not
change V1's runtime behaviour to make counting easier, so:

* action counters (clicks / blocked / misclicks / actions) come from the
  **trajectory**, which both loops write, so the numbers mean the same thing;
* plans / verification / recovery counters come from V2's event sink, and for
  V1 from trajectory markers + its existing log lines (raw log is kept).

Both adapters return the same ``RunStats`` dataclass, which is what the A/B
compares. Fields V1 never measured stay at 0 with a note in ``extra`` -- we do
not invent values for it.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence


@dataclass
class RunStats:
    plans: int = 0
    actions: int = 0
    clicks: int = 0          # clicks that actually reached the registry
    blocked: int = 0         # clicks stopped by a guard (never executed)
    misclicks: int = 0       # executed clicks whose target lacks the keyword
    recoveries_started: int = 0
    recoveries_completed: int = 0
    recoveries_ok: int = 0
    verifications: int = 0
    verifications_failed: int = 0
    events_source: str = ""
    extra: Dict = field(default_factory=dict)

    def as_dict(self) -> Dict:
        return dict(self.__dict__)


_ACTION_KEYS = {"success", "fail"}


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _keyword_hit(target, keyword: str) -> bool:
    if not target or not keyword:
        return True
    return keyword.lower() in str(target).lower()


# ── action counters: shared by both loops (trajectory) ──

def action_counts(trajectory: Sequence[Dict], keyword: str = "") -> RunStats:
    s = RunStats()
    for entry in trajectory or []:
        action = entry.get("action") or ""
        if action in _ACTION_KEYS or not action:
            continue
        blocked = bool(entry.get("target_violated")) or str(
            entry.get("reason") or "").startswith("blocked")
        if action == "click":
            if blocked:
                s.blocked += 1
                continue
            s.clicks += 1
            if entry.get("result_success") and not _keyword_hit(entry.get("target"), keyword):
                s.misclicks += 1
        if not blocked:
            s.actions += 1
    return s


# ── V2: structured events ──

def stats_from_events(events: Sequence[Dict]) -> RunStats:
    s = RunStats(events_source="events")
    for ev in events or []:
        etype = ev.get("type") or ""
        payload = ev.get("payload") or {}
        if etype == "plan_created":
            s.plans += 1
        elif etype == "verification":
            v = payload.get("verification") or {}
            s.verifications += 1
            if not v.get("success"):
                s.verifications_failed += 1
        elif etype == "recovery_started":
            s.recoveries_started += 1
        elif etype == "recovery_completed":
            rec = payload.get("recovery") or {}
            s.recoveries_completed += 1
            if rec.get("success"):
                s.recoveries_ok += 1
    return s


# ── V1: trajectory markers + existing log lines (behaviour untouched) ──

_LOG_RULES = [
    (re.compile(r"obstruction: context menu detected"), "obstruction"),
    (re.compile(r"action blocked by target visibility"), "target_invisible"),
    (re.compile(r"target visibility violated: clicking"), "target_invisible"),
    (re.compile(r"post-action context violated"), "context_mismatch"),
    (re.compile(r"SCROLL STALLED|scroll progress: candidates unchanged"), "scroll_no_progress"),
]


def stats_from_v1(trajectory: Sequence[Dict], log_text: str = "",
                  keyword: str = "") -> RunStats:
    s = action_counts(trajectory, keyword)
    s.events_source = "trajectory+log"
    reasons = set()
    for entry in trajectory or []:
        rec = entry.get("recovery")
        if rec:
            reasons.add(str(rec).split(":")[0])
        if entry.get("context_violated"):
            reasons.add("context_mismatch")
        sp = entry.get("scroll_progress")
        if isinstance(sp, dict) and sp.get("changed") is False:
            reasons.add("scroll_no_progress")
    for pattern, reason in _LOG_RULES:
        if pattern.search(log_text or ""):
            reasons.add(reason)
    s.recoveries_started = len(reasons)
    # V1 has no completion events: leaving these at 0 is the honest value.
    s.extra["v1_recovery_reasons"] = sorted(reasons)
    return s


def stats_for(record: Dict) -> RunStats:
    """Build one run's stats from its raw record (v1 or v2 shape)."""
    base = action_counts(record.get("trajectory") or [], record.get("keyword", ""))
    if record.get("events") is not None:
        evs = stats_from_events(record["events"])
        evs.actions, evs.clicks, evs.blocked, evs.misclicks = (
            base.actions, base.clicks, base.blocked, base.misclicks)
        return evs
    v1 = stats_from_v1(record.get("trajectory") or [],
                       record.get("log_text") or "",
                       record.get("keyword", ""))
    return v1
