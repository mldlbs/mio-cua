from typing import List


class History:
    def __init__(self):
        self.entries: List[dict] = []

    def record(self, action_id: str, type: str, ok: bool, message: str = ""):
        self.entries.append({"action_id": action_id, "type": type, "ok": ok, "message": message})

    def recent(self, n: int = 8) -> List[dict]:
        return self.entries[-n:]
