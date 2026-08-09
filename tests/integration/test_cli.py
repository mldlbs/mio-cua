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
