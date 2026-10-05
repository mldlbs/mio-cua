"""Phase 3 — canonical schema model: serialization, event ordering, redaction.

Covers spec §5-§13, §22, §30: round-trip of every dataclass, the Trace
container (events_of / recovery_events / steps / success), JSONL schema
version, and the privacy TraceRedactor.
"""

import pytest

from mio_cua.evaluation.schema import (
    SCHEMA_VERSION,
    ActionRecord,
    BeliefSnapshot,
    BenchmarkResult,
    FailureAttribution,
    FailureCandidate,
    ObservationSnapshot,
    PlanComparison,
    PlanSnapshot,
    ProgressRecord,
    RecoveryRecord,
    Trace,
    TraceEvent,
    TraceRedactor,
    VerificationRecord,
)


# ---- schema version --------------------------------------------------------


class TestSchemaVersion:
    def test_version_is_one(self):
        assert SCHEMA_VERSION == 1


# ---- snapshot dataclasses round-trip --------------------------------------


class TestSnapshotRoundTrip:
    def test_observation_snapshot(self):
        o = ObservationSnapshot(
            observation_id="o1", active_window="WeChat", screen_size=(800, 600),
            scene={"active_window": "WeChat", "nodes": [{"id": 1, "text": "a"}]},
            raw_elements=[{"id": 2, "text": "b"}],
        )
        o2 = ObservationSnapshot.from_dict(o.to_dict())
        assert o2.observation_id == "o1"
        assert o2.screen_size == (800, 600)
        assert o2.scene["nodes"][0]["text"] == "a"
        assert o2.raw_elements[0]["text"] == "b"

    def test_belief_snapshot(self):
        b = BeliefSnapshot(goal="g", current_state="s", expected_state="e",
                           confidence=0.5, known_entities=[{"c": "x"}], assumptions=["a"])
        b2 = BeliefSnapshot.from_dict(b.to_dict())
        assert b2.goal == "g"
        assert b2.confidence == 0.5
        assert b2.known_entities[0]["c"] == "x"

    def test_plan_snapshot(self):
        p = PlanSnapshot(intent="i", action_type="click", target="t",
                         parameters={"element_id": 3}, reasoning_summary="rs")
        p2 = PlanSnapshot.from_dict(p.to_dict())
        assert p2.action_type == "click"
        assert p2.parameters["element_id"] == 3

    def test_action_record(self):
        a = ActionRecord(action_id="a1", tool="click", parameters={"x": 1},
                         success=True, error=None)
        a2 = ActionRecord.from_dict(a.to_dict())
        assert a2.tool == "click"
        assert a2.success is True

    def test_verification_record(self):
        v = VerificationRecord(expected_state="e", observed_state="o",
                               success=False, confidence=0.3, evidence={"k": "v"})
        v2 = VerificationRecord.from_dict(v.to_dict())
        assert v2.success is False
        assert v2.evidence["k"] == "v"

    def test_progress_record(self):
        p = ProgressRecord(previous_state="a", current_state="b",
                           progress=0.5, changed=True, blocked=False)
        p2 = ProgressRecord.from_dict(p.to_dict())
        assert p2.changed is True
        assert p2.progress == 0.5

    def test_recovery_record(self):
        r = RecoveryRecord(reason="x", strategy="y", previous_action="z",
                           recovery_action="w", success=True)
        r2 = RecoveryRecord.from_dict(r.to_dict())
        assert r2.success is True
        assert r2.recovery_action == "w"

    def test_failure_attribution(self):
        fa = FailureAttribution(category="planner", confidence=0.9,
                                reason="r", evidence=["e"],
                                candidates=[FailureCandidate("planner", 0.9, "r")])
        fa2 = FailureAttribution.from_dict(fa.to_dict())
        assert fa2.category == "planner"
        assert fa2.candidates[0].category == "planner"

    def test_plan_comparison(self):
        c = PlanComparison(same_action=True, same_target=True,
                           parameter_delta={"x": {"recorded": 1, "replayed": 2}},
                           semantic_match=1.0)
        c2 = PlanComparison.from_dict(c.to_dict())
        assert c2.semantic_match == 1.0
        assert c2.parameter_delta["x"]["replayed"] == 2

    def test_benchmark_result(self):
        b = BenchmarkResult(total_tasks=3, success_tasks=2,
                            failure_distribution={"planner": 1},
                            success_rate=0.6667, average_steps=4.0)
        b2 = BenchmarkResult.from_dict(b.to_dict())
        assert b2.total_tasks == 3
        assert b2.failure_distribution["planner"] == 1


# ---- Trace container + accessors ------------------------------------------


class TestTraceContainer:
    def _ev(self, event_type, step, payload):
        return TraceEvent(event_type=event_type, step=step, payload=payload)

    def test_trace_event_round_trip(self):
        e = self._ev("plan_created", 2, {"plan": {"action_type": "click", "target": "t"}})
        e2 = TraceEvent.from_dict(e.to_dict())
        assert e2.event_type == "plan_created"
        assert e2.step == 2
        assert e2.payload["plan"]["action_type"] == "click"

    def test_trace_round_trip_with_failure(self):
        t = Trace(
            trace_id="t1", goal="find x",
            events=[self._ev("task_completed", 1, {"status": "SUCCESS"})],
            failure=FailureAttribution(category="planner", confidence=0.9,
                                       reason="r", evidence=[]),
            metadata={"target_context": {"keyword": "x"}},
        )
        t2 = Trace.from_dict(t.to_dict())
        assert t2.trace_id == "t1"
        assert t2.success is True
        assert t2.failure.category == "planner"
        assert t2.metadata["target_context"]["keyword"] == "x"

    def test_events_of_and_recovery(self):
        t = Trace(trace_id="t", events=[
            self._ev("recovery_started", 1, {"recovery": {"reason": "x"}}),
            self._ev("recovery_completed", 2, {"recovery": {"success": True}}),
            self._ev("observation", 3, {"observation": {"active_window": "W",
                                                        "scene": {"nodes": []}}}),
        ])
        assert len(t.events_of("observation")) == 1
        assert len(t.recovery_events()) == 2
        assert t.steps == 3

    def test_success_property_from_event(self):
        t = Trace(trace_id="t", events=[
            self._ev("task_completed", 1, {"status": "SUCCESS"}),
        ])
        assert t.success is True
        t2 = Trace(trace_id="t2", events=[
            self._ev("task_failed", 1, {"status": "FAIL"}),
        ])
        assert t2.success is False


# ---- TraceRedactor (privacy, spec §30) -------------------------------------


class TestTraceRedactor:
    def _trace_with_obs(self, nodes, raw):
        return Trace(trace_id="r", events=[
            TraceEvent(event_type="observation", step=0, payload={"observation": {
                "observation_id": "o", "active_window": "WeChat",
                "scene": {"nodes": nodes}, "raw_elements": raw,
            }})
        ])

    def test_redact_text_patterns(self):
        r = TraceRedactor(patterns=["SECRET"])
        assert r.redact_text("a SECRET b") == "a *** b"

    def test_redact_sensitive_keywords(self):
        trace = self._trace_with_obs(
            [{"id": 1, "text": "password 密码 here"}],
            [{"id": 2, "text": "password 密码 here"}],
        )
        red = TraceRedactor(sensitive_keywords=["密码"]).redact(trace)
        obs = red.events[0].payload["observation"]
        assert obs["scene"]["nodes"][0]["text"] == "***"
        assert obs["raw_elements"][0]["text"] == "***"

    def test_disable_raw_observation(self):
        trace = self._trace_with_obs(
            [{"id": 1, "text": "x"}],
            [{"id": 2, "text": "y"}],
        )
        red = TraceRedactor().disable_raw_observation().redact(trace)
        obs = red.events[0].payload["observation"]
        assert "raw_elements" not in obs
        assert obs["scene"].get("nodes") is None
        # original trace is untouched (redact returns a copy)
        assert trace.events[0].payload["observation"]["raw_elements"][0]["text"] == "y"

    def test_redact_is_non_destructive(self):
        trace = self._trace_with_obs(
            [{"id": 1, "text": "password 密码"}],
            [{"id": 2, "text": "password 密码"}],
        )
        TraceRedactor(sensitive_keywords=["密码"]).redact(trace)
        # original still has plain text
        assert "密码" in trace.events[0].payload["observation"]["scene"]["nodes"][0]["text"]
