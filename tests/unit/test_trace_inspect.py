"""Pure-function tests for ``mio_cua.evaluation.inspect`` (backs ``mio-cua history``).

No desktop, no LLM, no real input: traces are synthesised into ``tmp_path``
through the same ``JSONLTraceStore`` that ``run --record`` uses.
"""

import datetime as dt
import json
import os

from mio_cua.evaluation.inspect import (
    format_detail,
    format_table,
    load_summaries,
    summarize,
    summarize_dir,
)
from mio_cua.evaluation.recorder import JSONLTraceStore
from mio_cua.evaluation.schema import EventType, FailureAttribution, Trace, TraceEvent


def _trace(task_id, *, success, goal="do the thing", started="2026-08-26T10:00:00+00:00",
           finished="2026-08-26T10:00:30+00:00", failure=None):
    events = [
        TraceEvent(event_type=EventType.TASK_STARTED.value, step=0, payload={"goal": goal}),
        TraceEvent(event_type=EventType.OBSERVATION.value, step=1, payload={"active_window": "Notepad"}),
        TraceEvent(event_type=EventType.ACTION_STARTED.value, step=1, payload={"tool": "key"}),
        TraceEvent(event_type=EventType.ACTION_COMPLETED.value, step=1, payload={"tool": "key"}),
    ]
    if success:
        events.append(TraceEvent(event_type=EventType.TASK_COMPLETED.value, step=2,
                                 payload={"status": "SUCCESS"}))
    else:
        events.append(TraceEvent(event_type=EventType.TASK_FAILED.value, step=2,
                                 payload={"status": "FAILURE"}))
    return Trace(
        trace_id=task_id,
        task_id=task_id,
        goal=goal,
        started_at=dt.datetime.fromisoformat(started),
        finished_at=dt.datetime.fromisoformat(finished),
        events=events,
        result={"status": "SUCCESS" if success else "FAILURE",
                "summary": "done" if success else "no plan"},
        failure=failure,
    )


def _store(tmp_path):
    return JSONLTraceStore(str(tmp_path / "traces"))


def _save(store, trace):
    return store.save(trace)


# -- summarising -------------------------------------------------------------

def test_summarize_counts_events_and_duration(tmp_path):
    trace = _trace("t1", success=True)
    summary = summarize(trace, path="p")

    assert summary.task_id == "t1"
    assert summary.status == "SUCCESS"
    assert summary.steps == 5
    assert summary.event_counts["action_started"] == 1
    assert summary.duration_s == 30.0
    assert summary.failure_category == ""
    assert summary.result_summary == "done"


def test_summarize_keeps_failure_attribution():
    failure = FailureAttribution(category="planner", confidence=0.8, reason="no candidates")
    summary = summarize(_trace("t2", success=False, failure=failure), path="p")

    assert summary.status == "FAILURE"
    assert summary.failure_category == "planner"
    assert summary.failure_reason == "no candidates"
    assert summary.failure_confidence == 0.8


def test_summarize_dir_does_not_read_events(tmp_path):
    """Listing must stay cheap: steps stay unknown until the full trace is loaded."""
    store = _store(tmp_path)
    path = _save(store, _trace("t1", success=True))

    listing = summarize_dir(path)
    full = summarize(store.load(path), path=path)

    assert listing.steps is None
    assert full.steps == 5
    assert listing.task_id == full.task_id == "t1"


# -- listing -----------------------------------------------------------------

def test_load_summaries_is_newest_first(tmp_path):
    store = _store(tmp_path)
    _save(store, _trace("old", success=True, started="2026-08-01T00:00:00+00:00",
                        finished="2026-08-01T00:00:10+00:00"))
    _save(store, _trace("new", success=True, started="2026-09-01T00:00:00+00:00",
                        finished="2026-09-01T00:00:10+00:00"))

    ids = [s.task_id for s in load_summaries(str(tmp_path / "traces"))]
    assert ids == ["new", "old"]


def test_load_summaries_failed_only_and_limit(tmp_path):
    store = _store(tmp_path)
    _save(store, _trace("ok", success=True))
    _save(store, _trace("bad", success=False,
                        failure=FailureAttribution(category="action", confidence=0.5)))

    failed = load_summaries(str(tmp_path / "traces"), failed_only=True)
    limited = load_summaries(str(tmp_path / "traces"), limit=1)

    assert [s.task_id for s in failed] == ["bad"]
    assert len(limited) == 1


def test_load_summaries_skips_corrupt_trace(tmp_path):
    store = _store(tmp_path)
    _save(store, _trace("good", success=True))
    broken = tmp_path / "traces" / "2026-08-26" / "broken"
    broken.mkdir(parents=True)
    (broken / "metadata.json").write_text("{not json", encoding="utf8")

    summaries = load_summaries(str(tmp_path / "traces"))
    assert [s.task_id for s in summaries] == ["good"]


def test_load_summaries_missing_dir_is_empty(tmp_path):
    assert load_summaries(str(tmp_path / "nope")) == []


# -- rendering ---------------------------------------------------------------

def test_format_table_has_header_and_truncates_goal(tmp_path):
    store = _store(tmp_path)
    _save(store, _trace("t1", success=True, goal="x" * 80))

    table = format_table(load_summaries(str(tmp_path / "traces")))
    lines = table.splitlines()

    assert lines[0].split()[:3] == ["DATE", "TASK_ID", "STATUS"]
    assert "t1" in lines[1]
    assert "SUCCESS" in lines[1]
    assert "…" in lines[1]
    assert all(line == line.rstrip() for line in lines)


def test_format_detail_shows_failure_and_counts():
    failure = FailureAttribution(category="perception", confidence=0.75, reason="ocr empty")
    summary = summarize(_trace("t3", success=False, failure=failure), path="C:/traces/t3")

    text = format_detail(summary)

    assert "task t3" in text
    assert "steps 5" in text
    assert "perception" in text and "ocr empty" in text
    assert "action_started 1" in text
    assert "C:/traces/t3" in text


def test_format_detail_events_timeline():
    trace = _trace("t4", success=True)
    summary = summarize(trace, path="p")

    text = format_detail(summary, events=trace.events, include_events=True)

    assert "task_started" in text
    assert "active_window=Notepad" in text


def test_summary_to_dict_is_json_serialisable(tmp_path):
    store = _store(tmp_path)
    path = _save(store, _trace("t5", success=False,
                               failure=FailureAttribution(category="planner", confidence=0.4)))
    payload = summarize(store.load(path), path=path).to_dict()

    round_trip = json.loads(json.dumps(payload, ensure_ascii=False))
    assert round_trip["task_id"] == "t5"
    assert round_trip["failure"]["category"] == "planner"
    assert round_trip["steps"] == 5


def test_summarize_handles_missing_timestamps():
    trace = Trace(trace_id="t6", task_id="t6", goal="", started_at=None, finished_at=None)
    summary = summarize(trace)

    assert summary.duration_s is None
    assert summary.started_at == ""
