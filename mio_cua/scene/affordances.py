"""Affordance Builder: generate concrete click/type candidates from Nodes.

Affordances are produced by the perception layer via generic UI rules, not
inferred by the LLM. The ``expected`` field records what the action should
observably change (e.g. the calculator display value) so the loop can verify
success via Scene Diff.

Display inference: a large "readout" region (right-aligned large text with few
words) is treated as the window's result display. Digit/operator buttons that
are adjacent to it get an ``expected.display`` hint; otherwise the display is
still recorded as a diff-able node.
"""

import re

from mio_cua.scene.graph import Affordance

_DIGIT_RE = re.compile(r"^[0-9]+$")
_OPERATOR_RE = re.compile(r"^[+\-*/=x.%×÷−＋]+$")

# Chinese/UIA localized operator names (the on-screen glyph is often a
# non-ASCII symbol that merger keeps out in favour of the UIA label).
_OPERATOR_WORDS = {"乘以", "乘", "除以", "除", "减", "减去", "加", "加上", "等号", "等于"}

# Dialog field labels: short text ending with a full/half-width colon and an
# optional hotkey suffix, e.g. `文件名(N):`, `文件名：`. Modern dialogs expose
# the neighbouring edit box only as OCR text, so we infer it is typeable.
_FIELD_LABEL_RE = re.compile(r"^[^\s:：]{1,12}[：:]\s*$")

_DISPLAY_MIN_WIDTH = 150
_DISPLAY_MIN_HEIGHT = 40

# Short dialog button labels that OCR commonly surfaces as plain `text` nodes
# (Win11 modern dialogs expose few UIA controls). Text matching these -- with
# an optional hotkey suffix like `保存(S)` or `Cancel` -- becomes clickable.
_BUTTON_WORDS = {
    "save", "open", "ok", "确定", "取消", "保存", "另存为", "yes", "no",
    "apply", "apply all", "安装", "安装到", "重试", "retry", "cancel",
    "关闭", "close", "完成", "done", "下一步", "next", "上一步", "back",
    "继续", "continue", "登录", "登录/注册", "sign in", "sign up", "submit",
    "发送", "send", "搜索", "search", "下载", "download", "知道了",
    "got it", "agree", "同意", "删除", "delete", "rename", "重命名",
}


def _bbox(bbox):
    return tuple(int(v) for v in bbox)


def _center(bbox):
    left, top, width, height = _bbox(bbox)
    return (left + width / 2, top + height / 2)


class AffordanceBuilder:
    def __init__(self, nodes, relations):
        self.nodes = nodes
        self.relations = relations

    def build(self) -> tuple:
        """Return (affordances, display_ids)."""
        affordances = []
        display_ids = self._find_display()
        display_bbox = None
        if display_ids:
            dnode = next((n for n in self.nodes if n.id == display_ids[0]), None)
            if dnode is not None:
                display_bbox = dnode.bbox

        for n in self.nodes:
            if not n.state.get("enabled", True):
                continue
            text = (n.semantic or n.text or "").strip()
            if n.type == "button":
                a = self._button_affordance(n, text)
                if display_bbox and a is not None:
                    self._add_display_expected(a, text, display_bbox, n)
                if a is not None:
                    affordances.append(a)
            elif n.type == "input":
                affordances.append(Affordance(
                    node_id=n.id, action="type",
                    params={"into": n.id}, confidence=self._conf(n),
                ))
            elif n.type == "text" and self._is_button_word(text):
                # Modern dialogs often expose buttons only as OCR text nodes;
                # make clearly-actionable labels clickable.
                affordances.append(Affordance(
                    node_id=n.id, action="click", params={},
                    confidence=self._conf(n),
                ))

        for a in self._dialog_field_affordances():
            affordances.append(a)

        return affordances, display_ids

    @staticmethod
    def _is_button_word(text: str) -> bool:
        t = text.strip()
        if not t:
            return False
        # strip an optional hotkey suffix, e.g. `保存(S)`, `Save (S)`.
        core = re.sub(r"\(\s*[A-Za-z\u4e00-\u9fff]?\s*\)$", "", t).strip()
        core = core.lower()
        return core in _BUTTON_WORDS

    def _conf(self, n):
        return max(0.3, min(1.0, n.confidence))

    def _dialog_field_affordances(self):
        """Give type candidates to edit boxes that OCR only saw as text.

        A node that looks like a field label (`文件名(N):`) marks the text
        node to its right (same row) as an editable field, so the LLM can
        ``type`` into it instead of guessing by clicking.
        """
        affs = []
        seen = set()
        by_id = {n.id: n for n in self.nodes}
        for n in self.nodes:
            if n.type != "text":
                continue
            text = (n.semantic or n.text or "").strip()
            if not _FIELD_LABEL_RE.match(text) or self._is_button_word(text):
                continue
            field = self._field_after_label(n, by_id)
            if field is None or field.id in seen:
                continue
            seen.add(field.id)
            field.type = "input"  # render as an editable box in the scene
            affs.append(Affordance(
                node_id=field.id, action="type",
                params={"into": field.id}, confidence=self._conf(field),
            ))
        return affs

    def _field_after_label(self, label, by_id):
        """Return the text node that is the edit box right of ``label``."""
        lx, ly, lw, lh = label.bbox
        lcy = ly + lh / 2.0

        def same_row(f):
            _, fy, _, fh = f.bbox
            return abs(fy + fh / 2.0 - lcy) <= max(lh, fh) * 1.5 + 24

        def is_value(f):
            ft = (f.semantic or f.text or "").strip()
            return (bool(ft) and not self._is_button_word(ft)
                    and not _FIELD_LABEL_RE.match(ft))

        cands = []
        for rel in self.relations:
            if rel.source != label.id or rel.kind not in ("leftOf", "near", "labelFor"):
                continue
            f = by_id.get(rel.target)
            if f is not None and f.type == "text" and is_value(f) and same_row(f):
                cands.append(f)
        if not cands:
            for f in self.nodes:
                if f.id == label.id or f.type != "text" or not is_value(f) or not same_row(f):
                    continue
                gap = f.bbox[0] - (lx + lw)
                if -20 <= gap <= 500:
                    cands.append(f)
        if not cands:
            return None
        cands.sort(key=lambda f: (f.bbox[1], abs(f.bbox[0] - (lx + lw))))
        return cands[0]

    def _button_affordance(self, n, text):
        action = "click"
        params = {}
        expected = {}
        is_op = _OPERATOR_RE.match(text) or text in _OPERATOR_WORDS
        if _DIGIT_RE.match(text):
            params = {"value": text}
        elif is_op:
            params = {"value": text}
            # Pressing an operator (×/÷/+/−) does NOT change the display: it
            # records the pending operation and waits for the next operand.
            # Tell the model so it does not treat an unchanged display as a
            # missed click and repeat the operator.
            expected = {"display": "unchanged"}
        a = Affordance(
            node_id=n.id, action=action, params=params,
            confidence=self._conf(n),
        )
        if expected:
            a.expected.update(expected)
        return a

    def _find_display(self):
        """Pick nodes that look like a numeric/result readout (large text)."""
        best = None
        for n in self.nodes:
            if n.type not in ("text", "input", "group"):
                continue
            w, h = n.bbox[2], n.bbox[3]
            text = (n.semantic or n.text or "").strip()
            if w < _DISPLAY_MIN_WIDTH or h < _DISPLAY_MIN_HEIGHT:
                continue
            # A readout is short: few words, mostly digits/symbols.
            words = text.split()
            if len(words) <= 4 and any(re.search(r"[0-9]", w) for w in words):
                score = w * h
                if best is None or score > best[0]:
                    best = (score, n.id)
        return [best[1]] if best else []

    def _add_display_expected(self, affordance, text, display_bbox, node):
        """Digit buttons near the display imply the display should change.

        Operators already mark ``expected.display == "unchanged"`` (pressing
        them does not alter the readout); do not clobber that with True.
        """
        dx, dy = _center(display_bbox)
        nx, ny = _center(node.bbox)
        # Buttons below/left of the display are "input" for it.
        if affordance.expected.get("display") != "unchanged" and ny > dy + 10 and abs(nx - dx) < display_bbox[2]:
            affordance.expected["display"] = True
