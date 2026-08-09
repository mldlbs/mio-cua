import os

_PROMPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load(name: str) -> str:
    with open(os.path.join(_PROMPT_DIR, name), "r", encoding="utf8") as f:
        return f.read()


DEFAULT_SYSTEM_PROMPT = load("system.txt")
