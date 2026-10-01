import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mio_cua.perception.perception import Perception


def main():
    p = Perception()
    for label, fn in (("observe      ", "observe"), ("observe_light", "observe_light")):
        times = []
        for i in range(2):
            t = time.time()
            obs = getattr(p, fn)()
            dt = time.time() - t
            times.append(dt)
            print(
                f"{label} #{i}: {dt:6.1f}s  window={getattr(obs, 'active_window', None)!r} "
                f"proc={getattr(obs, 'active_process', None)!r} "
                f"nodes={len(getattr(getattr(obs, 'scene', None), 'nodes', []) or [])} "
                f"elements={len(getattr(obs, 'elements', None) or [])}"
            )
        print(f"{label} mean={sum(times) / len(times):.1f}s\n")


if __name__ == "__main__":
    main()
