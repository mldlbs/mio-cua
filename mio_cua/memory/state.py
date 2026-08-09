import json
import os


def state_path(state_dir: str, task_id: str) -> str:
    return os.path.join(state_dir, f"{task_id}.json")


class TaskState:
    def __init__(self, path: str):
        self.path = path

    def save(self, task_id: str, instruction: str, step: int, screenshot: str = ""):
        data = {"task_id": task_id, "instruction": instruction, "step": step, "screenshot": screenshot}
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r", encoding="utf8") as f:
            return json.load(f)
