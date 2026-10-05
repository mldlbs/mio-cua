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
