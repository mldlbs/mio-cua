from mio_cua.config import AgentConfig


def test_defaults_and_overrides():
    cfg = AgentConfig(model="gpt-4o-mini")
    assert cfg.model == "gpt-4o-mini"
    assert cfg.max_steps == 50
    assert cfg.provider == "openai"


def test_from_yaml(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text("model: qwen-vl\nmax_steps: 10\n", encoding="utf8")
    cfg = AgentConfig.from_yaml(str(p))
    assert cfg.model == "qwen-vl"
    assert cfg.max_steps == 10
    assert cfg.provider == "openai"  # defaults still apply


def test_api_key_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret")
    cfg = AgentConfig.from_yaml(str(tmp_path / "nope.yaml"))
    cfg.data["api_key_env"] = "MY_KEY"
    assert cfg.api_key() == "secret"


def test_batch_defaults():
    cfg = AgentConfig()
    assert cfg.batch_limit == 3
    assert cfg.batch_verify is True


def test_batch_overrides():
    cfg = AgentConfig(batch_limit=1, batch_verify=False)
    assert cfg.batch_limit == 1
    assert cfg.batch_verify is False
