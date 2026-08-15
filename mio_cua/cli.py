import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mio-cua")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run a task")
    run.add_argument("instruction", nargs="+")
    run.add_argument("--provider")
    run.add_argument("--model")
    run.add_argument("--base-url")
    run.add_argument("--config", help="path to yaml config")
    run.add_argument("--dry-run", action="store_true", help="plan only, no input")
    run.add_argument("--simulate", action="store_true", help="run loop on a scripted desktop, no real input")
    run.add_argument("--simulate-full", action="store_true", help="run full loop against a stateful mock desktop")
    run.add_argument("--scenario", default="notepad", help="mock scenario for --simulate-full: notepad|calculator|explorer")
    run.add_argument("--simulate-scenario", help="path to a scenario YAML to replay offline (no real input)")

    resume = sub.add_parser("resume", help="Resume a previous task")
    resume.add_argument("task_id")

    replay = sub.add_parser("replay", help="Replay/debug a task from saved artifacts")
    replay.add_argument("task_id")
    replay.add_argument("--full", action="store_true", help="include action params and result metadata")

    sub.add_parser("providers", help="List available providers")

    gen = sub.add_parser("gen-scenario", help="Generate a YAML scenario from a screenshot")
    gen.add_argument("--image", help="path to a PNG screenshot (OCR-only)")
    gen.add_argument("--capture", action="store_true", help="capture the active window (merged OCR+UIA)")
    gen.add_argument("--name", default="", help="scenario name (default: file basename)")
    gen.add_argument("-o", "--output", required=True, help="output YAML path")

    history = sub.add_parser("history", help="Show task history")
    history.add_argument("task_id", nargs="?")

    return parser


def main():
    args = build_parser().parse_args()
    if args.cmd == "providers":
        print("openai")
        return
    if args.cmd == "gen-scenario":
        _gen_scenario_command(args)
        return
    if args.cmd == "run":
        _run_command(args)
    elif args.cmd == "resume":
        _resume_command(args)
    elif args.cmd == "replay":
        _replay_command(args)
    elif args.cmd == "history":
        print(f"history {args.task_id or ''}".strip())


def _replay_command(args):
    from mio_cua.config import AgentConfig
    from mio_cua.memory.artifact import ArtifactStore

    store = ArtifactStore(AgentConfig().artifact_dir)
    entries = store.artifacts_for(args.task_id)
    if not entries:
        print(f"no artifacts for task {args.task_id}")
        return
    print(f"task {args.task_id}: {len(entries)} steps")
    for i, entry in enumerate(entries, 1):
        data = entry["data"]
        action = data.get("action") or {}
        result = data.get("result") or {}
        typ = action.get("type", "?")
        params = action.get("params") or {}
        ok = result.get("success", False)
        msg = result.get("message", "")
        extra = f" params={params}" if args.full else ""
        meta = f" metadata={result.get('metadata')}" if (args.full and result.get("metadata")) else ""
        print(f"[{i:02d}] {typ}{extra} -> {'OK' if ok else 'FAIL'} {msg}{meta}")


def _resume_command(args):
    import os

    from mio_cua.config import AgentConfig
    from mio_cua.memory.state import TaskState, state_path
    from mio_cua.models.task import Task

    config = AgentConfig()
    st = TaskState(state_path(os.path.join(config.artifact_dir, "state"), args.task_id))
    data = st.load()
    if not data:
        print(f"no saved state for task {args.task_id}")
        return
    print(f"task {args.task_id}: {data.get('instruction')!r} (reached step {data.get('step')})")

    from mio_cua import Agent
    agent = Agent(config)
    result = agent.run(Task(instruction=data["instruction"]))
    print(f"{result.status} steps={result.steps} duration={result.duration:.1f}s")


def _run_command(args):
    from mio_cua.config import AgentConfig
    from mio_cua.models.task import Task

    config = AgentConfig()
    if args.config:
        config = AgentConfig.from_yaml(args.config)
    overrides = {}
    if args.model:
        overrides["model"] = args.model
    if args.provider:
        overrides["provider"] = args.provider
    if args.base_url:
        overrides["base_url"] = args.base_url
    if overrides:
        config = AgentConfig(**{**config.data, **overrides})

    task = Task(instruction=" ".join(args.instruction))
    if args.dry_run:
        print(f"[dry-run] would run: {task.instruction}")
        return
    if args.simulate:
        _simulate_command(config, task)
        return
    if args.simulate_full:
        _simulate_full_command(config, task, args.scenario)
        return
    if args.simulate_scenario:
        _simulate_scenario_command(config, task, args.simulate_scenario)
        return

    from mio_cua import Agent
    agent = Agent(config)
    result = agent.run(task)
    print(f"{result.status} steps={result.steps} duration={result.duration:.1f}s")


def _simulate_command(config, task):
    """Show one planning pass against a scripted notepad observation (no real input)."""
    from mio_cua.agent.planner import Planner
    from mio_cua.models.element import Element
    from mio_cua.models.observation import Observation
    from mio_cua.prompts import DEFAULT_SYSTEM_PROMPT
    from mio_cua.providers.openai_compat import OpenAICompatProvider
    from mio_cua.tools.builtin import register_builtin_tools
    from mio_cua.tools.registry import ToolRegistry

    editor = Element(0, "uia", text="", role="Document", bbox=(370, 264, 500, 200))
    field = Element(1, "uia", text="无标题", role="TabItem", bbox=(400, 200, 120, 20))
    obs = Observation(None, 1.0, "无标题 - 记事本", 1.0, [field, editor])

    provider = OpenAICompatProvider(config.base_url, config.api_key(), config.model)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    planner = Planner(provider, DEFAULT_SYSTEM_PROMPT)
    plan = planner.plan(task, obs, None, registry.schemas())
    print(f"thought: {plan.thought or ''}")
    for a in plan.actions:
        print(f"  [plan] {a.type} {a.params}")
    if not plan.actions:
        print("  (no actions planned)")


def _gen_scenario_command(args):
    """Generate a YAML scenario from a screenshot (--image) or the active window (--capture)."""
    import os
    import sys
    from mio_cua.scenario import scenario_to_yaml

    name = args.name or (os.path.splitext(os.path.basename(args.image))[0] if args.image else "capture")
    if args.image:
        if not os.path.isfile(args.image):
            print(f"error: image not found: {args.image}")
            sys.exit(1)
        from PIL import Image
        from mio_cua.vision import ocr as ocr_module
        img = Image.open(args.image)
        elements = list(ocr_module.get_elements(img))
        source = "ocr"
        active_window = ""
    elif args.capture:
        from mio_cua.perception import Perception
        obs = Perception().observe()
        elements = obs.elements
        active_window = obs.active_window or ""
        source = "merged"
    else:
        print("error: provide --image <path> or --capture")
        sys.exit(1)

    yaml_text = scenario_to_yaml(elements, active_window=active_window, name=name, source=source)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf8") as f:
        f.write(yaml_text)
    print(f"wrote scenario '{name}' ({len(elements)} elements) -> {args.output}")


def _simulate_full_command(config, task, scenario="notepad"):
    """Run the whole loop against a stateful mock desktop; no real input is sent."""
    from mio_cua.agent.safety import Safety
    from mio_cua.events import EventBus
    from mio_cua.prompts import DEFAULT_SYSTEM_PROMPT
    from mio_cua.providers.openai_compat import OpenAICompatProvider
    from mio_cua.simulation import build_mock_desktop
    from mio_cua.tools.builtin import register_builtin_tools
    from mio_cua.tools.registry import ToolRegistry

    provider = OpenAICompatProvider(config.base_url, config.api_key(), config.model)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    safety = Safety(max_steps=config.max_steps, timeout_s=config.task_timeout_s,
                    emergency_key=config.emergency_key)
    loop, desktop = build_mock_desktop(
        provider, DEFAULT_SYSTEM_PROMPT, registry, safety, EventBus(), config, scenario=scenario,
    )
    result = loop.run(task)
    print(f"[{scenario}] {result.status} steps={result.steps} duration={result.duration:.1f}s")
    print(f"mock completed: {desktop.completed}")
    for action in desktop.actions:
        print(f"  [act] {action.type} {action.params}")


def _simulate_scenario_command(config, task, scenario_path):
    """Replay a scenario YAML through the loop with no real input."""
    import sys
    from mio_cua.agent.safety import Safety
    from mio_cua.events import EventBus
    from mio_cua.prompts import DEFAULT_SYSTEM_PROMPT
    from mio_cua.providers.openai_compat import OpenAICompatProvider
    from mio_cua.scenario import load_scenario_yaml
    from mio_cua.simulation import build_simulation
    from mio_cua.tools.builtin import register_builtin_tools
    from mio_cua.tools.registry import ToolRegistry

    try:
        obs = load_scenario_yaml(scenario_path)
    except ValueError as e:
        print(f"error: {e}")
        sys.exit(1)
    provider = OpenAICompatProvider(config.base_url, config.api_key(), config.model)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    safety = Safety(max_steps=config.max_steps, timeout_s=config.task_timeout_s,
                    emergency_key=config.emergency_key)
    loop, controller = build_simulation(
        provider, DEFAULT_SYSTEM_PROMPT, [obs], registry, safety, EventBus(), config,
    )
    result = loop.run(task)
    print(f"[scenario] {result.status} steps={result.steps} duration={result.duration:.1f}s")
    for action in controller.calls:
        print(f"  [act] {action.type} {action.params}")


if __name__ == "__main__":
    main()
