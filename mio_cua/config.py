import os
from typing import Any, Dict

import yaml

DEFAULTS: Dict[str, Any] = {
    "provider": "openai",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY",
    "max_steps": 50,
    "task_timeout_s": 300,
    "emergency_key": "f9",
    "artifact_dir": os.path.expanduser("~/.mio_cua/artifacts"),
    "artifact_max_bytes": 200 * 1024 * 1024,
}


class AgentConfig:
    def __init__(self, **overrides):
        self.data: Dict[str, Any] = {**DEFAULTS, **overrides}

    def __getattr__(self, name: str):
        if name in self.data:
            return self.data[name]
        raise AttributeError(name)

    def api_key(self) -> str:
        return os.environ.get(str(self.data["api_key_env"]), "")

    @classmethod
    def from_yaml(cls, path: str) -> "AgentConfig":
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf8") as f:
                data = yaml.safe_load(f) or {}
        return cls(**data)
