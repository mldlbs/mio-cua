from mio_cua.models.action import Action, Plan
from mio_cua.providers.base import Provider


def _tool_routing_hint(active_window):
    """Suggest the deterministic tool channel for the current window type.

    The agent should use filesystem tools for file work instead of clicking
    around Explorer, and keyboard/shortcuts where they beat pixel clicks.
    This makes the 'vision for decisions, tools for execution' split explicit
    at each step.
    """
    t = (active_window or "").lower()
    if any(k in t for k in ("资源管理器", "文件资源管理器", "explorer")):
        return ("ROUTING: this is a File Explorer window. For file operations "
                "(listing, creating folders, moving files) use the filesystem "
                "tools list_dir/make_dir/move_file -- they are deterministic "
                "and far more reliable than clicking/dragging in Explorer.")
    return None


class Planner:
    def __init__(self, provider: Provider, system_prompt: str):
        self.provider = provider
        self.system_prompt = system_prompt
        self._counter = 0

    def plan(self, task, observation, diff, tools: list, history=None, hints=None) -> Plan:
        obs_text = _summarize(observation)
        instruction = getattr(task, "instruction", "") or ""
        user_content = f"Task: {instruction}\nActive window: {observation.active_window}\n{obs_text}"
        routing = _tool_routing_hint(observation.active_window)
        if routing:
            user_content += "\n" + routing
        if diff is not None and diff.changes:
            user_content += "\nRecent changes: " + "; ".join(c.description for c in diff.changes)
        if history is not None:
            recent = history.recent(8)
            if recent:
                parts = []
                for h in recent:
                    mark = "OK" if h.get("ok") else "FAIL"
                    line = f"{h['type']} {mark}"
                    msg = (h.get("message") or "").strip()
                    if msg and h.get("ok"):
                        line += f" -> {msg[:220]}"
                    parts.append(line)
                user_content += "\nTool results (from your recent actions):\n" + "\n".join(parts)
        if hints:
            user_content += "\n" + "\n".join(f"GUIDANCE: {h}" for h in hints)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        image_msg = None
        if observation.screenshot_path:
            user_content += "\nThe attached screenshot shows red boxes numbered by element id; prefer element_id when targeting them."
            image_msg = _image_message(observation.screenshot_path)
            messages.append(image_msg)
        try:
            resp = self.provider.generate(messages, tools=tools)
        except Exception as e:
            if image_msg is not None and getattr(getattr(e, "response", None), "status_code", None) == 400:
                # non-vision provider (e.g. DeepSeek): drop the screenshot and retry
                messages.remove(image_msg)
                resp = self.provider.generate(messages, tools=tools)
            else:
                raise
        actions = []
        for tc in resp.tool_calls:
            self._counter += 1
            actions.append(Action(id=f"a-{self._counter:06d}", type=tc.name, params=tc.arguments))
        return Plan(thought=resp.message, goal=user_content, actions=actions)


def _summarize(observation) -> str:
    """Render the observation as a Scene Graph plus action candidates.

    If the observation carries a SceneGraph (perception layer), we print nodes,
    key relations, display nodes and the affordances the perception layer
    already computed, so the LLM picks actions instead of guessing geometry.
    Falls back to the flat element list when no scene is present.
    """
    scene = getattr(observation, "scene", None)
    if scene is not None and getattr(scene, "nodes", None):
        return _summarize_scene(scene)
    return _summarize_flat(observation)


def _summarize_scene(scene) -> str:
    lines = []
    by_id = {n.id: n for n in scene.nodes}
    regions = getattr(scene, "regions", None) or []
    if regions:
        lines.append("## Layout regions (page structure)")
        from mio_cua.scene.regions import regions_summary
        rs = regions_summary(regions)
        if rs:
            lines.append(rs)
    lines.append("## Scene")
    for n in scene.nodes:
        flags = []
        if n.type and n.type != "unknown":
            flags.append(n.type)
        if not n.state.get("enabled", True):
            flags.append("disabled")
        if n.id in scene.display_ids:
            flags.append("display")
        label = n.semantic or n.text or f"({n.type or 'element'})"
        lines.append(f"- id={n.id} {label!r} {' '.join(flags)} bbox={n.bbox}")
    if scene.affordances:
        lines.append("## Action candidates (already verified by perception)")
        for a in scene.affordances:
            n = by_id.get(a.node_id)
            label = (n.semantic or n.text) if n else "?"
            line = f"- {a.action} node {a.node_id} ({label!r})"
            if a.params:
                line += f" {a.params}"
            if a.expected:
                line += f" expects {a.expected}"
            lines.append(line)
    # A few high-value relations to disambiguate geometry.
    important = [r for r in scene.relations
                 if r.kind in ("labelFor", "leftOf", "above")]
    for r in important[:20]:
        src = by_id.get(r.source)
        tgt = by_id.get(r.target)
        if src is None or tgt is None:
            continue
        lines.append(f"- rel {r.kind}: {(src.semantic or src.text or src.id)!r} -> {(tgt.semantic or tgt.text or tgt.id)!r}")
    if not lines:
        return "(no elements detected)"
    return "\n".join(lines)


def _summarize_flat(observation) -> str:
    """Legacy flat element rendering, kept for observations without a scene."""
    seen = set()
    deduped = []
    for e in observation.elements:
        if e.bbox is None:
            continue
        left, top, width, height = e.bbox
        if width <= 0 or height <= 0:
            continue
        text = (e.text or "").strip()
        sig = (e.role or "", text, round(left / 10), round(top / 10),
               round(width / 10), round(height / 10))
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append((e, text))
    # Text-bearing elements first (OCR digits, button labels); empty UIA
    # containers last so they are the ones dropped when we cap the list.
    deduped.sort(key=lambda pair: (0 if pair[1] else 1,))
    lines = []
    for e, text in deduped[:120]:
        flags = []
        if e.role and e.role != "unknown":
            flags.append(e.role)
        if not e.enabled:
            flags.append("disabled")
        label = text or f"({e.role or 'element'})"
        lines.append(f"- id={e.id} {label!r} {' '.join(flags)} bbox={e.bbox}")
    if not lines:
        return "(no elements detected)"
    return "\n".join(lines)


def _image_message(path: str) -> dict:
    import base64
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]}
