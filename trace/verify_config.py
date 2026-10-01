from mio_cua.config import AgentConfig

if hasattr(AgentConfig, "model_fields"):  # pydantic v2
    names = list(AgentConfig.model_fields)
elif hasattr(AgentConfig, "__dataclass_fields__"):
    names = list(AgentConfig.__dataclass_fields__)
else:
    names = list(getattr(AgentConfig, "__annotations__", {}))
required = (
    "base_url",
    "api_key_env",
    "model",
    "max_steps",
    "task_timeout_s",
    "artifact_dir",
    "runtime_v2",
)
for k in required:
    print(f"{k:16} {'OK' if k in names else 'MISSING'}")

c = AgentConfig(
    base_url="http://127.0.0.1:8000/p/zen",
    api_key_env="ZEN_API_KEY",
    model="hy3-free",
    max_steps=20,
    task_timeout_s=600,
    artifact_dir="trace/artifacts_v2",
    runtime_v2=False,
)
print("build OK ->", c.model, c.base_url, "runtime_v2=", c.runtime_v2)
