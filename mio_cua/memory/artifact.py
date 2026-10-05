import dataclasses
import json
import os
import time
import uuid

from pathlib import Path


def to_dict(obj):
    """Recursively convert dataclasses/nested containers to plain dicts for JSON."""
    if dataclasses.is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


class ArtifactStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self._counter = 0

    def _path(self, name: str):
        os.makedirs(self.base_dir, exist_ok=True)
        return os.path.join(self.base_dir, name)

    def save_artifact(self, obs=None, action=None, result=None, task_id=None):
        # Windows clock granularity (~15ms) can collide; add a monotonic seq for
        # deterministic ordering within a process.
        self._counter += 1
        ts = time.time()
        data = {
            "observation": to_dict(obs),
            "action": to_dict(action),
            "result": to_dict(result),
            "task_id": task_id,
            "timestamp": ts,
            "seq": self._counter,
        }
        name = f"{int(ts * 1000)}_{uuid.uuid4().hex[:8]}.json"
        path = self._path(name)
        with open(path, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        return Path(path)

    def artifacts_for(self, task_id: str) -> list:
        """Return [{path, data}] for a task, oldest first."""
        if not os.path.isdir(self.base_dir):
            return []
        found = []
        for name in os.listdir(self.base_dir):
            if not name.endswith(".json"):
                continue
            p = os.path.join(self.base_dir, name)
            try:
                with open(p, "r", encoding="utf8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if data.get("task_id") == task_id:
                found.append({"path": p, "data": data})
        found.sort(key=lambda x: (x["data"].get("timestamp", 0), x["data"].get("seq", 0)))
        return found

    def prune(self, max_bytes: int) -> int:
        """Delete oldest files (recursively) until the dir is under max_bytes.

        Returns how many bytes were freed. Keeps the most recent artifacts,
        which is what replay/debugging needs.
        """
        if not os.path.isdir(self.base_dir):
            return 0
        files = []
        for root, _dirs, names in os.walk(self.base_dir):
            for name in names:
                p = os.path.join(root, name)
                try:
                    files.append((os.path.getmtime(p), os.path.getsize(p), p))
                except OSError:
                    continue
        files.sort()
        total = sum(sz for _, sz, _ in files)
        freed = 0
        for _, sz, p in files:
            if total <= max_bytes:
                break
            try:
                os.remove(p)
                total -= sz
                freed += sz
            except OSError:
                continue
        return freed
