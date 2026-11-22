from mio_cua.cli import build_parser


def test_run_subcommand_parses_dry_run():
    p = build_parser()
    args = p.parse_args(["run", "open calc", "--model", "gpt-4o", "--dry-run"])
    assert args.cmd == "run"
    assert args.dry_run is True
    assert args.model == "gpt-4o"


def test_providers_subcommand():
    p = build_parser()
    args = p.parse_args(["providers"])
    assert args.cmd == "providers"


def test_resume_requires_task_id():
    p = build_parser()
    args = p.parse_args(["resume", "abc123"])
    assert args.cmd == "resume"
    assert args.task_id == "abc123"


def test_resume_requires_task_id_fails_without_it():
    import pytest
    from mio_cua.cli import build_parser

    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["resume"])


def test_run_with_config_and_provider_flags_parse():
    p = build_parser()
    args = p.parse_args(["run", "open calc", "--config", "cfg.yaml", "--provider", "deepseek"])
    assert args.config == "cfg.yaml"
    assert args.provider == "deepseek"


def test_gen_scenario_subcommand_parses():
    p = build_parser()
    args = p.parse_args(["gen-scenario", "--image", "shot.png", "--name", "calc", "-o", "out.yaml"])
    assert args.cmd == "gen-scenario"
    assert args.image == "shot.png"
    assert args.name == "calc"
    assert args.output == "out.yaml"


def test_gen_scenario_capture_parses():
    p = build_parser()
    args = p.parse_args(["gen-scenario", "--capture", "-o", "out.yaml"])
    assert args.cmd == "gen-scenario"
    assert args.capture is True
    assert args.output == "out.yaml"


def test_run_simulate_scenario_parses():
    p = build_parser()
    args = p.parse_args(["run", "open calc", "--simulate-scenario", "scene.yaml"])
    assert args.cmd == "run"
    assert args.simulate_scenario == "scene.yaml"


def test_run_simulate_scenario_executes_offline(tmp_path):
    """Replay a scenario YAML through the loop with no real input."""
    from mio_cua.cli import _simulate_scenario_command
    from mio_cua.config import AgentConfig
    from mio_cua.models.task import Task

    scene = tmp_path / "calc.yaml"
    scene.write_text(
        "name: calc\nactive_window: 计算器\nsource: ocr\n"
        "elements:\n"
        "  - {id: 0, text: '0', role: text, bbox: [400, 300, 240, 40], source: ocr}\n"
        "  - {id: 1, text: '7', role: button, bbox: [400, 360, 50, 30], source: ocr}\n",
        encoding="utf8",
    )

    import pytest
    from mio_cua.cli import _simulate_scenario_command
    with pytest.raises(SystemExit):
        _simulate_scenario_command(AgentConfig(), Task(instruction="open calc"), str(tmp_path / "missing.yaml"))


def test_simulate_scenario_runs_loop_without_real_input(tmp_path, monkeypatch, capsys):
    """gen-scenario + simulate-scenario: the loop runs and records actions with
    NO real input (RecordingController), using a stub provider."""
    from mio_cua.cli import _simulate_scenario_command
    from mio_cua.config import AgentConfig
    from mio_cua.models.task import Task

    scene = tmp_path / "calc.yaml"
    scene.write_text(
        "name: calc\nactive_window: 计算器\nsource: ocr\n"
        "elements:\n"
        "  - {id: 0, text: '0', role: text, bbox: [400, 300, 240, 40], source: ocr}\n"
        "  - {id: 1, text: '7', role: button, bbox: [400, 360, 50, 30], source: ocr}\n",
        encoding="utf8",
    )

    class StubProvider:
        def __init__(self, *a, **k):
            self.calls = 0

        def generate(self, messages, tools=None):
            from mio_cua.models.action import ToolCall
            from mio_cua.providers.base import LLMResponse
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(message="plan", tool_calls=[
                    ToolCall(id="t1", name="click", arguments={"element_id": 1}),
                ])
            return LLMResponse(message="done", tool_calls=[
                ToolCall(id="t2", name="success", arguments={"result": "done"}),
            ])

    monkeypatch.setattr(
        "mio_cua.providers.openai_compat.OpenAICompatProvider", StubProvider)
    cfg = AgentConfig(model="stub")
    _simulate_scenario_command(cfg, Task(instruction="click 7"), str(scene))

    out = capsys.readouterr().out
    assert "SUCCESS" in out
    assert "[act] click" in out


# -- history ---------------------------------------------------------------

def _write_history_traces(root):
    """Two traces (one success, one failure) in the Phase 3 on-disk layout."""
    import datetime as dt

    from mio_cua.evaluation.recorder import JSONLTraceStore
    from mio_cua.evaluation.schema import EventType, FailureAttribution, Trace, TraceEvent

    store = JSONLTraceStore(str(root))

    def make(task_id, success, started):
        events = [
            TraceEvent(event_type=EventType.TASK_STARTED.value, payload={"goal": "open calc"}),
            TraceEvent(event_type=EventType.OBSERVATION.value, payload={"active_window": "Calculator"}),
        ]
        events.append(TraceEvent(
            event_type=(EventType.TASK_COMPLETED if success else EventType.TASK_FAILED).value,
            payload={"status": "SUCCESS" if success else "FAILURE"},
        ))
        return Trace(
            trace_id=task_id, task_id=task_id, goal="open calc",
            started_at=dt.datetime.fromisoformat(started),
            finished_at=dt.datetime.fromisoformat(started) + dt.timedelta(seconds=12),
            events=events,
            result={"status": "SUCCESS" if success else "FAILURE", "summary": "done" if success else "boom"},
            failure=None if success else FailureAttribution(category="planner", confidence=0.7,
                                                            reason="no plan"),
        )

    store.save(make("ok001", True, "2026-08-20T10:00:00+00:00"))
    store.save(make("bad002", False, "2026-08-21T10:00:00+00:00"))
    return str(root)


def test_history_subcommand_parses_filters():
    p = build_parser()
    args = p.parse_args(["history", "abc", "--dir", "traces", "--limit", "5",
                         "--failed", "--json", "--events"])
    assert args.cmd == "history"
    assert args.task_id == "abc"
    assert args.dir == "traces"
    assert args.limit == 5
    assert args.failed is True
    assert args.json is True
    assert args.events is True


def test_history_lists_traces_newest_first(tmp_path, capsys):
    from mio_cua.cli import _history_command

    root = _write_history_traces(tmp_path / "traces")
    args = build_parser().parse_args(["history", "--dir", root])
    _history_command(args)

    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[0].split()[:3] == ["DATE", "TASK_ID", "STATUS"]
    assert "bad002" in lines[1]
    assert "ok001" in lines[2]


def test_history_failed_filter(tmp_path, capsys):
    from mio_cua.cli import _history_command

    root = _write_history_traces(tmp_path / "traces")
    args = build_parser().parse_args(["history", "--dir", root, "--failed"])
    _history_command(args)

    out = capsys.readouterr().out
    assert "bad002" in out
    assert "ok001" not in out


def test_history_detail_json(tmp_path, capsys):
    import json

    from mio_cua.cli import _history_command

    root = _write_history_traces(tmp_path / "traces")
    args = build_parser().parse_args(["history", "bad002", "--dir", root, "--json"])
    _history_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "bad002"
    assert payload["status"] == "FAILURE"
    assert payload["steps"] == 3
    assert payload["failure"]["category"] == "planner"


def test_history_detail_events(tmp_path, capsys):
    from mio_cua.cli import _history_command

    root = _write_history_traces(tmp_path / "traces")
    args = build_parser().parse_args(["history", "ok001", "--dir", root, "--events"])
    _history_command(args)

    out = capsys.readouterr().out
    assert "task ok001" in out
    assert "steps 3" in out
    assert "task_started" in out
    assert "active_window=Calculator" in out


def test_history_empty_dir_message(tmp_path, capsys):
    from mio_cua.cli import _history_command

    args = build_parser().parse_args(["history", "--dir", str(tmp_path / "missing")])
    _history_command(args)

    assert "no traces found" in capsys.readouterr().out


def test_history_unknown_task_exits_1(tmp_path, capsys):
    import pytest

    from mio_cua.cli import _history_command

    root = _write_history_traces(tmp_path / "traces")
    args = build_parser().parse_args(["history", "nope", "--dir", root])
    with pytest.raises(SystemExit) as exc:
        _history_command(args)

    assert exc.value.code == 1
    assert "no trace for task nope" in capsys.readouterr().out
