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
    "batch_limit": 3,       # 一个 plan 内最多连续执行的非终止动作数
    "batch_verify": True,   # 批次内每步做轻量实时验证；False 退化为「一观察一动作」
    "runtime_v2": False,    # 使用 Agent Runtime v2 (Belief/Progress/Recovery) 替代 v1 的 if-else invariant
    # --- LLM 调用韧性：共享代理会成片返回 429/503，重试预算太短会让整轮任务死掉 ---
    "llm_timeout_s": 180,        # 单次请求超时（推理模型实测 60-93s）
    "llm_attempts": 4,           # 总尝试次数（含首次）
    "llm_backoff_s": 0.5,        # 指数退避基数：0.5, 1, 2, 4, ...
    "llm_backoff_max_s": 30.0,   # 单次退避上限（也会遵守响应里的 Retry-After）
    # --- A/B 实验层开关：A/B/C/D 逐层打开时使用，默认全开（不影响旧行为）---
    "enable_grounding": True,     # False -> InputController 不挂 Grounder（版本 A 裸执行）
    "enable_verification": True,  # False -> 关闭批次内实时验证（版本 B）
    "enable_recovery": True,      # False -> 关闭确定性 Recovery（版本 A/B/C）
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
