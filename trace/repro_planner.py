import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mio_cua.agent.planner import Planner
from mio_cua.config import AgentConfig
from mio_cua.models.task import Task
from mio_cua.perception.perception import Perception
from mio_cua.providers.openai_compat import OpenAICompatProvider


def _load_key():
    p = Path(__file__).resolve().parent.parent / ".llm_env"
    for line in p.read_text(encoding="utf8").splitlines():
        if line.startswith("CK_API_KEY="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("CK_API_KEY", "")


class SizedProvider(OpenAICompatProvider):
    """Records the exact request body size before sending it."""

    last_size = 0
    last_image_bytes = 0

    def generate(self, messages, tools=None):
        body = {"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": 4096}
        if tools:
            body["tools"] = tools
        raw = json.dumps(body)
        SizedProvider.last_size = len(raw)
        img = 0
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        img = max(img, len(url))
        SizedProvider.last_image_bytes = img
        print(f"  request body: {len(raw) / 1024:.0f} KiB "
              f"(image dataurl {img / 1024:.0f} KiB, messages={len(messages)}, tools={len(tools or [])})")
        try:
            return super().generate(messages, tools=tools)
        except Exception as e:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
            body = ""
            if resp is not None:
                try:
                    body = resp.text[:600]
                except Exception:
                    pass
            print(f"  !! generate FAILED: {type(e).__name__}: status={status}")
            if body:
                print(f"     body: {body}")
            raise


def main():
    cfg = AgentConfig(
        base_url="https://ai.crlkcloud.cyou/v1",
        api_key_env="CK_API_KEY",
        model="default",
        max_steps=20,
        task_timeout_s=60,
    )
    os.environ.setdefault("CK_API_KEY", _load_key())

    provider = SizedProvider(base_url=cfg.base_url, api_key=cfg.api_key(), model=cfg.model, timeout=60)
    planner = Planner(provider, "You are a desktop GUI agent.")

    print("observing...")
    t = time.time()
    obs = Perception(screenshot_dir=str(Path(__file__).resolve().parent / "_repro_shots")).observe()
    print(f"observe: {time.time() - t:.1f}s window={obs.active_window!r} "
          f"proc={obs.active_process!r} elements={len(obs.elements)} "
          f"screenshot={obs.screenshot_path!r}")

    task = Task(
        instruction="打开浏览器，在搜索引擎中搜索「今日新闻」",
        target_context={"app": "Edge"},
    )
    tools = [{"name": "click", "parameters": {"type": "object"}},
             {"name": "focus_window", "parameters": {"type": "object"}}]

    print("planning (with image):")
    try:
        plan = planner.plan(task, obs, None, tools)
        print(f"  OK actions={[a.type for a in plan.actions]} size={SizedProvider.last_size}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        print(f"  body size was {SizedProvider.last_size} KiB "
              f"(image {SizedProvider.last_image_bytes / 1024:.0f} KiB)")

        print("\nretrying WITHOUT the screenshot:")
        obs.screenshot_path = None
        try:
            plan = planner.plan(task, obs, None, tools)
            print(f"  OK actions={[a.type for a in plan.actions]}")
        except Exception as e2:
            print(f"  STILL FAILED: {type(e2).__name__}: {e2} size={SizedProvider.last_size}")


if __name__ == "__main__":
    main()
