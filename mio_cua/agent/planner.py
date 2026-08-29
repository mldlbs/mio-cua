import json
from dataclasses import dataclass, field
from mio_cua.models.action import Action, Plan
from mio_cua.providers.base import Provider


@dataclass
class ExplorationState:
    """Track exploration progress across Planner calls.

    Detects when the agent is stuck (no viewport/candidate changes)
    and suggests strategy switches.
    """
    previous_target_visible: bool = False
    viewport_hash: str = ""
    candidate_hash: str = ""
    no_progress_count: int = 0
    strategy_history: list = field(default_factory=list)  # ["scroll", "search", ...]

    def update(self, target_visible: bool, viewport_hash: str, candidate_hash: str):
        """Update state after each observation. Returns True if progress was made."""
        # First call: no previous state, count as no progress
        if not self.viewport_hash and not self.candidate_hash:
            self.previous_target_visible = target_visible
            self.viewport_hash = viewport_hash
            self.candidate_hash = candidate_hash
            self.no_progress_count = 0
            return True

        progress = True
        if (viewport_hash == self.viewport_hash
                and candidate_hash == self.candidate_hash
                and not target_visible):
            self.no_progress_count += 1
            progress = False
        else:
            self.no_progress_count = 0
        self.previous_target_visible = target_visible
        self.viewport_hash = viewport_hash
        self.candidate_hash = candidate_hash
        return progress

    def should_switch_strategy(self) -> bool:
        return self.no_progress_count >= 3

    def next_strategy(self) -> str:
        """Suggest next strategy based on history."""
        if "search" not in self.strategy_history:
            self.strategy_history.append("search")
            return "search"
        self.strategy_history.append("replan")
        return "replan"


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
        self._exploration = ExplorationState()

    @property
    def exploration_state(self):
        """Expose exploration state for TraceRecorder."""
        e = self._exploration
        return {
            "target_visible": e.previous_target_visible,
            "no_progress_count": e.no_progress_count,
            "should_switch": e.should_switch_strategy(),
            "strategy_history": list(e.strategy_history),
        }

    def plan(self, task, observation, diff, tools: list, history=None, hints=None) -> Plan:
        obs_text = _summarize(observation)
        instruction = getattr(task, "instruction", "") or ""

        # Build structured context state (hard constraint, not text)
        target = getattr(task, "target_context", None) or {}
        target_app = target.get("app") or target.get("window", "")
        active_window = observation.active_window or ""
        # Context match: exact title match OR process name match via aliases
        _ALIASES = {"wechat": "微信", "chrome": "Chrome", "firefox": "Firefox", "edge": "Edge"}
        target_proc = _ALIASES.get(target_app.lower(), "")
        context_verified = bool(
            target_app and (
                active_window.lower() == target_app.lower()
                or target_proc and target_proc in active_window.lower()
            )
        )

        context_state = {
            "active_app": active_window,
            "target_app": target_app or None,
            "context_verified": context_verified,
        }

        user_content = f"Task: {instruction}\n{json.dumps({'context_state': context_state}, ensure_ascii=False, indent=1)}\n{obs_text}"
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
        # Compute exploration state hints from observation + task
        expl_hints = self._exploration_hints(observation, task)
        if expl_hints:
            hints = list(hints or []) + expl_hints
        if hints:
            user_content += "\n" + "\n".join(f"GUIDANCE: {h}" for h in hints)
        # Context invariant: hard constraint, not natural language
        if not context_verified and target_app:
            user_content += (
                f"\n=== INVARIANT (违反 = 任务失败) ===\n"
                f"context_verified=false: 目标应用 '{target_app}' 不在当前窗口.\n"
                f"你必须先调用 focus_window(title='{target_app}')，等下一次 observation 确认 context_verified=true 后再继续.\n"
                f"禁止在 context_verified=false 时执行任何其他操作.\n"
                f"=========================="
            )
        elif context_verified:
            user_content += (
                f"\n=== CONTEXT STATE ===\n"
                f"context_verified=true: 当前窗口已是 '{active_window}'.\n"
                f"禁止调用 focus_window(title='{active_window}') — 窗口已聚焦.\n"
                f"直接在当前窗口中执行任务.\n"
                f"=========================="
            )
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
            status = getattr(getattr(e, "response", None), "status_code", None)
            if image_msg is not None and status in (400, 404):
                # non-vision provider: drop the screenshot and retry
                messages.remove(image_msg)
                resp = self.provider.generate(messages, tools=tools)
            else:
                raise
        actions = []
        for tc in resp.tool_calls:
            self._counter += 1
            actions.append(Action(id=f"a-{self._counter:06d}", type=tc.name, params=tc.arguments))
        return Plan(thought=resp.message, goal=user_content, actions=actions)

    def _exploration_hints(self, observation, task):
        """Compute exploration state hints based on observation and task.

        General navigation state: target_visible, context_valid, exploration_available.
        Returns list of hint strings. Empty if no keyword or target is visible.
        """
        keyword = (getattr(task, "metadata", None) or {}).get("keyword", "")
        if not keyword:
            return []

        # Check target visibility in scene
        scene = getattr(observation, "scene", None)
        nodes = getattr(scene, "nodes", []) or []
        visible_texts = []
        for n in nodes:
            text = (getattr(n, "text", "") or "").strip()
            if text:
                visible_texts.append(text.lower())
        for e in getattr(observation, "elements", []) or []:
            text = (getattr(e, "text", "") or "").strip()
            if text:
                visible_texts.append(text.lower())

        keyword_lower = keyword.lower()
        target_visible = any(keyword_lower in t for t in visible_texts)

        # Compute normalized viewport signature (robust to OCR noise)
        viewport_hash = _viewport_signature(nodes, observation)
        candidate_hash = str(sorted([n.id for n in nodes]))

        # Update exploration state
        self._exploration.update(target_visible, viewport_hash, candidate_hash)

        if target_visible:
            return [
                f"TARGET FOUND: '{keyword}' is visible. "
                f"Click the matching element by element_id."
            ]

        # Target not visible — exploration needed
        # Fuzzy search detection: check text AND scene affordances
        _SEARCH_KW = {"搜索", "search", "查找", "find", "查询", "query", "搜"}
        has_search = any(
            any(kw in t for kw in _SEARCH_KW)
            for t in visible_texts
        )
        # Also check scene affordances for search purpose
        if not has_search and hasattr(observation, "scene"):
            for a in getattr(observation.scene, "affordances", []):
                if a.params.get("purpose") == "search":
                    has_search = True
                    break
        hints = []

        # Check if stuck (no progress for 3 steps)
        if self._exploration.should_switch_strategy():
            next_s = self._exploration.next_strategy()
            if next_s == "search":
                hints.append(
                    f"STUCK: no progress after {self._exploration.no_progress_count} steps. "
                    f"SWITCH TO SEARCH: click the search box, type '{keyword}', press Enter."
                )
            else:
                hints.append(
                    f"STUCK: search and scroll both failed. "
                    f"Try a different approach or request help."
                )
        else:
            exploration_type = []
            if has_search:
                exploration_type.append("search box (click it, type the keyword, press Enter)")
            if len(nodes) > 5:
                exploration_type.append("scroll")
            affordance_str = " or ".join(exploration_type) if exploration_type else "no exploration affordance detected"

            hints.append(
                f"TARGET NOT VISIBLE: '{keyword}' is not in the current view. "
                f"Available: {affordance_str}. "
                f"Do NOT click any element that doesn't contain '{keyword}'."
            )

        return hints


def _normalize_text(text):
    """Normalize text for viewport signature: lowercase, strip, remove pure digits/timestamps."""
    import re
    t = (text or "").strip().lower()
    # Remove timestamps like "14:03" or "(180054ms)"
    t = re.sub(r'\d{1,2}:\d{2}', '', t)
    t = re.sub(r'\(\d+ms\)', '', t)
    # Remove pure numeric strings (IDs, counts)
    if re.match(r'^[\d\s]+$', t):
        return ''
    return t.strip()


def _viewport_signature(nodes, observation):
    """Compute a normalized viewport signature robust to OCR noise.

    Uses: normalized text + quantized bbox region + semantic role.
    Ignores: exact text variations, timestamps, confidence fluctuations.
    """
    import re
    signatures = []
    for n in (nodes or []):
        text = _normalize_text(getattr(n, "text", ""))
        if not text:
            continue
        bbox = getattr(n, "bbox", None) or [0, 0, 0, 0]
        # Quantize bbox to 20px grid (reduces noise from sub-pixel shifts)
        qx = (bbox[0] // 20) * 20 if len(bbox) > 0 else 0
        qy = (bbox[1] // 20) * 20 if len(bbox) > 1 else 0
        ntype = getattr(n, "type", "") or ""
        nsem = (getattr(n, "semantic", "") or "").lower()
        # Use semantic role (input/button/text) not exact semantic name
        role = "input" if "input" in ntype or "search" in nsem or "box" in nsem else ntype
        sig = f"{text}|{qx},{qy}|{role}"
        signatures.append(sig)
    # Also include flat elements
    for e in getattr(observation, "elements", []) or []:
        text = _normalize_text(getattr(e, "text", ""))
        if not text:
            continue
        bbox = getattr(e, "bbox", None) or [0, 0, 0, 0]
        qx = (bbox[0] // 20) * 20 if len(bbox) > 0 else 0
        qy = (bbox[1] // 20) * 20 if len(bbox) > 1 else 0
        sig = f"{text}|{qx},{qy}|element"
        signatures.append(sig)
    return str(sorted(signatures))


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


def _scene_summary(scene) -> str:
    """Generate a high-level semantic summary of the UI scene.

    Helps the LLM understand the UI structure without guessing from raw node text.
    """
    nodes = getattr(scene, "nodes", []) or []
    # Classify nodes
    text_nodes = []
    input_nodes = []
    button_nodes = []
    group_count = 0
    for n in nodes:
        ntype = (getattr(n, "type", "") or "").lower()
        nsem = (getattr(n, "semantic", "") or "").lower()
        if ntype == "group" or "mmuirendersubwindow" in nsem or "weixin" in nsem:
            group_count += 1
            continue
        text = (getattr(n, "text", "") or "").strip()
        if not text:
            continue
        if "input" in ntype or "search" in nsem or "box" in nsem:
            input_nodes.append(text)
        elif "button" in ntype or "link" in ntype:
            button_nodes.append(text)
        else:
            text_nodes.append(text)

    # Detect search affordance — fuzzy match
    _SEARCH_KW = {"搜索", "search", "查找", "find", "查询", "query", "搜"}
    has_search = any(
        any(kw in t for kw in _SEARCH_KW)
        for t in text_nodes + input_nodes
    )
    # Also check scene affordances for search purpose
    if not has_search:
        for a in getattr(scene, "affordances", []):
            if a.params.get("purpose") == "search":
                has_search = True
                break
    # Layout fallback: list pattern (multiple text nodes in left column) → search likely exists
    if not has_search and len(text_nodes) >= 3:
        has_search = True  # assume search exists in list views

    # Build summary
    parts = [f"## Scene Summary ({len(nodes)} nodes, {len(text_nodes)} with text)"]
    if text_nodes:
        # Show first few readable texts as context
        preview = text_nodes[:8]
        parts.append(f"Visible text: {', '.join(t[:25] for t in preview)}{'...' if len(text_nodes) > 8 else ''}")
    if input_nodes:
        parts.append(f"Input fields: {', '.join(t[:25] for t in input_nodes[:3])}")
    if button_nodes:
        parts.append(f"Buttons: {', '.join(t[:25] for t in button_nodes[:3])}")
    has_search_str = "yes" if has_search else "no"
    parts.append(f"Search affordance: {has_search_str}")

    return "\n".join(parts)


def _summarize_scene(scene) -> str:
    lines = []
    by_id = {n.id: n for n in scene.nodes}
    regions = getattr(scene, "regions", None) or []

    # Semantic summary: high-level UI structure
    lines.append(_scene_summary(scene))

    if regions:
        lines.append("## Layout regions (page structure)")
        from mio_cua.scene.regions import regions_summary
        rs = regions_summary(regions)
        if rs:
            lines.append(rs)
    # Window-relative layout: the active app frame defines the sidebar, not an
    # absolute x<300 (the window may sit on a secondary screen at x>=800, e.g.
    # WeChat at x=840). Use the frame bbox so the chat list lands in the
    # sidebar section instead of being mislabeled as the main panel.
    win_bbox = None
    for n in scene.nodes:
        if getattr(n, "type", "") == "group" and (
            "MMUIRenderSubWindow" in (getattr(n, "semantic", "") or "")
            or "Weixin" in (getattr(n, "semantic", "") or "")
        ):
            win_bbox = n.bbox
            break
    if win_bbox is None:
        for n in scene.nodes:
            if getattr(n, "type", "") == "group" and n.bbox:
                win_bbox = n.bbox
                break
    sidebar_right = (win_bbox[0] + int(win_bbox[2] * 0.5)) if win_bbox else 300

    # Structural inference: group nodes by region
    left_items = []  # sidebar / chat-list elements
    right_items = []  # main panel elements
    for n in scene.nodes:
        bbox = n.bbox
        if not bbox or len(bbox) < 4:
            continue
        # Skip window/container frame nodes — they are the app frame, never a
        # clickable chat, and presenting them invites the agent to click id=0/1.
        ntype = getattr(n, "type", "") or ""
        nsem = (getattr(n, "semantic", "") or "").lower()
        if ntype == "group" or "mmuirendersubwindow" in nsem or "weixin" in nsem:
            continue
        x, y, w, h = bbox
        text = getattr(n, "text", "") or ""
        if x < sidebar_right and text.strip():
            left_items.append(n)
        elif x >= sidebar_right and text.strip():
            right_items.append(n)
    if left_items:
        lines.append("## Left sidebar (chat list) — click a chat item here to open it")
        for n in left_items[:20]:
            label = n.semantic or n.text or f"({n.type or 'element'})"
            lines.append(f"- id={n.id} {label!r} bbox={n.bbox}")
    if right_items:
        lines.append("## Main panel")
        for n in right_items[:30]:
            label = n.semantic or n.text or f"({n.type or 'element'})"
            lines.append(f"- id={n.id} {label!r} bbox={n.bbox}")
    lines.append("## Scene (all nodes)")
    for n in scene.nodes:
        ntype = getattr(n, "type", "") or ""
        nsem = (getattr(n, "semantic", "") or "").lower()
        if ntype == "group" or "mmuirendersubwindow" in nsem or "weixin" in nsem:
            # App frame / container — not a clickable element; omit so the model
            # does not target it as a chat or button.
            continue
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
