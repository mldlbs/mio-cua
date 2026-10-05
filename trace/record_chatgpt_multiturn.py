"""Multi-turn ChatGPT: does reply extraction survive a long thread?

The single-turn recorder anchors on one fixed prompt fragment ("介绍你自己")
and returns everything between that anchor and the composer. Over N turns the
fragment matches every message of ours and the band fills with earlier turns,
so this script does three things differently:

  * turns are a REAL conversation -- 12 topic threads whose lines each depend
    on the previous one ("为什么推荐成都" only works after the recommendation),
    because independent trivia questions never exercise the way a live thread
    scrolls, quotes back, and grows;
  * every message carries a unique token (R201..R300) at its START, and
    extraction anchors on that -- position, not wording, separates our line
    from the reply;
  * the thread openers ask the model to append the same token to each reply,
    so a non-empty extraction can be checked for identity: if R237 comes back,
    we extracted turn 237's reply and not some earlier one.

Usage: python trace/record_chatgpt_multiturn.py --turns 100 --from 201
       (--limit is only a runaway-reply ceiling for under_limit; it is no
       longer injected into the prompts -- real follow-ups are not scripted
       to stay within N characters)
"""
import argparse
import ctypes
import json
import re
import sys
import time
from pathlib import Path

TRACE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TRACE_DIR))
sys.path.insert(0, str(TRACE_DIR.parent))
sys.stdout.reconfigure(encoding="utf-8")

import win32gui  # noqa: E402

import record_chatgpt_chat as base  # noqa: E402
from mio_cua.automation.input_controller import InputController  # noqa: E402
from mio_cua.automation.windows import _focus_latest, focus_window  # noqa: E402
from mio_cua.models.action import Action  # noqa: E402
from mio_cua.perception import column  # noqa: E402
from mio_cua.perception.perception import Perception  # noqa: E402

# Real conversational threads: every line depends on the one before it
# ("为什么推荐成都" only makes sense after the recommendation). Threads open
# by (re-)stating the convention that replies end with the message's
# leading number -- that is what keeps `tagged` verifiable ~every 10 turns
# without turning each line into the same formulaic instruction.
THREADS = [
    ("旅行", [
        "先聊聊旅行吧，你推荐国内哪个城市。以后每条回复末尾都带上我消息开头的编号，方便我做记录",
        "为什么推荐成都",
        "成都有什么必吃的",
        "那重庆呢，跟成都比怎么样",
        "两个只能去一个的话你选哪个",
        "大概玩几天比较合适",
        "旺季住宿会不会很贵",
        "有推荐的周边景点吗",
        "只有两天的话怎么安排",
        "冬天去合适吗",
        "换我先说，我其实更想去海边，你觉得呢",
        "那厦门呢，值得专门跑一趟吗",
        "厦门几天够玩",
        "从成都到厦门飞机多久",
    ]),
    ("美食", [
        "说说吃的吧，家常菜里你最拿手哪道。对了，回复末尾还是带上我消息开头的编号",
        "那道菜最关键的一步是什么",
        "没有烤箱能做吗",
        "换个方向，火锅和烤肉你选哪个",
        "为什么",
        "那川菜和湘菜的区别在哪",
        "你能吃辣吗",
        "微辣算不算辣",
        "夜宵一般吃什么好",
        "半夜吃太咸会不会水肿",
    ]),
    ("电影", [
        "最近有什么电影值得看吗。记住每条回复末尾带上我消息开头的编号",
        "国产片里呢",
        "那部讲的是什么",
        "是喜剧吗",
        "评分高吗",
        "导演还拍过什么",
        "类似风格的还有吗",
        "如果只推荐一部你推哪部",
        "为什么是这部",
        "纪录片也说一部吧",
    ]),
    ("读书", [
        "最近在读书吗，有推荐的吗。回复末尾记得带编号",
        "这本书讲的是什么",
        "难读吗",
        "和作者的其他书比呢",
        "电子版好找吗",
        "你一般读纸质书还是电子书",
        "为什么",
        "一天大概能读多少页",
        "那读完要多久",
        "读完接下来读什么",
    ]),
    ("运动", [
        "聊聊运动吧，你现在有规律锻炼吗。每条回复末尾带编号",
        "一周几次比较合理",
        "跑步和游泳哪个更适合新手",
        "为什么",
        "膝盖不好还能跑步吗",
        "那做什么比较好",
        "在家能练吗",
        "没有器械怎么练",
        "每次练多久",
        "多久能看到效果",
    ]),
    ("AI 编程", [
        "说说 AI 编程工具吧，你觉得哪个好用。回复末尾带编号",
        "为什么是它",
        "贵吗",
        "新手上手难吗",
        "它能自己写测试吗",
        "会不会写出来的代码有坑",
        "那怎么避免",
        "你自己平时用什么模型",
        "模型之间差别大吗",
        "以后程序员会被取代吗",
    ]),
    ("宠物", [
        "想养个宠物，猫和狗选哪个好。每条回复末尾带编号",
        "猫要每天遛吗",
        "掉毛严重吗",
        "那狗呢，金毛好养吗",
        "金毛拆家吗",
        "一个月大概花多少钱",
        "租房能养吗",
        "房东一般会同意吗",
        "过敏体质怎么办",
        "领养好还是买好",
    ]),
    ("历史", [
        "聊点历史吧，你最喜欢哪个朝代。回复末尾带编号",
        "为什么是唐朝",
        "那个朝代有什么大事",
        "当时的皇帝是谁",
        "他干了什么",
        "结局怎么样",
        "如果能穿越回去你想去哪",
        "去了能活过三集吗",
        "换个外国的，你对哪个时期感兴趣",
        "那个时期有什么特别的",
    ]),
    ("科学", [
        "问个科学问题，为什么天是蓝的。回复末尾带编号",
        "那晚霞为什么是红的",
        "下雨前为什么会闷",
        "打雷又是怎么回事",
        "闪电和雷同时发生，为什么先看到闪电",
        "声音传播有多快",
        "那光呢",
        "所以先看到闪电是正常的",
        "极光是怎么形成的",
        "在哪里能看到",
    ]),
    ("职场", [
        "聊聊工作吧，你觉得什么样的领导算好。回复末尾带编号",
        "怎么判断领导好不好",
        "加班多算不算差",
        "该不该跟领导谈加薪",
        "怎么开口比较合适",
        "被拒绝了怎么办",
        "那跳槽呢，什么时候该走",
        "多久跳一次算频繁",
        "简历有空窗期怎么解释",
        "面试被问缺点怎么答",
        "最后一题，第一份工作选大公司还是小公司",
    ]),
    ("音乐", [
        "听听音乐，你最近单曲循环哪首。回复末尾带编号",
        "什么风格的",
        "谁唱的",
        "为什么喜欢它",
        "是歌词好还是旋律好",
        "有中文的推荐吗",
        "跑步的时候适合听什么",
        "睡前听什么比较好",
        "你会听老歌吗",
        "推荐一首你心中的神曲",
    ]),
    ("消费", [
        "说说花钱吧，你觉得什么钱最值得花。回复末尾带编号",
        "那什么钱最不值",
        "电子产品你会追新吗",
        "为什么",
        "衣服呢，你在意牌子吗",
        "网购多还是线下多",
        "怎么避免冲动消费",
        "双十一你会囤货吗",
        "视频会员值得开吗",
        "最后一问，一个月存多少钱算合理",
    ]),
]

_FLAT = [ln for _, lines in THREADS for ln in lines]

# Optional fixed script (--prompts-file): overrides the THREADS rotation, one
# message per line, indexed relative to --from. Used for short deep threads
# (5-round discussions) where every line is hand-written instead of rotated.
_PROMPTS: list = []
_PROMPT_BASE = 1


def line_for(k: int) -> str:
    if _PROMPTS:
        return _PROMPTS[(k - _PROMPT_BASE) % len(_PROMPTS)]
    return _FLAT[(k - 1) % len(_FLAT)]


def token_of(k: int) -> str:
    return f"R{k:03d}"


def prompt_for(k: int) -> str:
    """Turn k's message: unique token FIRST, then the contextual line.

    Position is load-bearing -- ``_is_our_message`` anchors on the token
    opening the message, which is the only thing that separates our line
    from the reply that echoes the same token at its end.
    """
    return f"{token_of(k)} {line_for(k)}"


def _chrome_hwnds():
    out = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1":
            return
        if win32gui.GetWindowText(hwnd):
            out.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return out


def _activate(hwnd) -> bool:
    """Raise ``hwnd`` and verify it is THE foreground window, not merely that
    some window of its process is.

    _focus_latest treats "a window from the same process became foreground"
    as success (a UWP workaround) -- with two Chrome windows competing that
    is a lie: the sibling kept the top spot, clicks went to it, and turns
    split across TWO different conversations (R007-R009 in one chat id,
    R023-R203 in the other). So force SwitchToThisWindow until the exact
    hwnd holds the foreground; a window we cannot raise must not be driven.
    """
    if not _focus_latest([hwnd]):
        return False
    for _ in range(3):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
        time.sleep(0.15)
    return win32gui.GetForegroundWindow() == hwnd


def looks_like_chatgpt(obs) -> bool:
    """Recognise the page by content, not by window title.

    Site is selected by the module-global ``SITE`` (``--site``): the ChatGPT
    run must ignore DeepSeek windows and vice versa -- both sit in Chrome and
    both would otherwise match in the unpinned fallback, which is exactly how
    a quota-blocked ChatGPT window could steal the send.

    ChatGPT traps this has to avoid:

    * ChatGPT sets <title> from the conversation, so after the first message
      the caption reads e.g. '自我介绍[assistant]=1.5? ...' and no longer
      contains 'ChatGPT'.
    * Electron apps (OpenCode, WorkBuddy, VS Code) share Chrome's window
      class, so enumerating ``Chrome_WidgetWin_1`` also returns them -- and
      their nodes happened to contain the same detection words. The owning
      process must therefore be checked first: only a real browser counts.
    * the footer disclaimer ("也可能会犯错") is NOT always on screen: with
      the sidebar open it vanished entirely and a whole run failed to find
      any window. The address bar URL is stable, so it leads; the disclaimer
      is only a fallback alongside the sidebar's "新聊天".

    DeepSeek has no such title games, but its composer placeholder OCRs to a
    single garbage character, so the URL leads and the sidebar/toolbar
      markers (开启新对话 + 深度思考) are only a fallback.
    """
    if "chrome" not in (getattr(obs, "active_process", "") or "").lower():
        return False
    texts = [(t or "") for _, t, _ in base._node_tuples(obs)]
    host = "deepseek.com" if SITE == "deepseek" else "chatgpt.com"
    if any(host in t for t in texts):
        return True
    if SITE == "deepseek":
        return any("深度思考" in t for t in texts) and any(
            "开启新对话" in t for t in texts
        )
    if not any("随便问" in t for t in texts):
        return False
    return any(("也可能会犯错" in t) or ("新聊天" in t) for t in texts)


_CHATGPT_HWND = {"hwnd": None}

# Which chat site this run drives (``--site``). A module global because every
# helper -- recognition, focus, layout, the report's scenario name -- must
# agree on one site per run; mixing them in one pass is how a dead ChatGPT
# window would swallow the DeepSeek send.
SITE = "chatgpt"


def _tree_has(obs, needle) -> bool:
    return any(needle in (t or "") for _, t, _ in base._node_tuples(obs))


def focus_chatgpt(perception, pin_token=None, _fallback=False):
    """(ok, how, obs) -- obs is reusable, so the caller need not observe again.

    ``pin_token`` is the PREVIOUS turn's token. Two Chrome windows can sit on
    chatgpt.com with DIFFERENT conversations open (turns split across them
    once already), so domain-level recognition is not enough: the window that
    already contains the last turn's token is unambiguously ours. If no
    window carries the pin (first turn of a fresh chat, or the previous send
    failed) fall back to any ChatGPT window and say so in ``how``.

    The hwnd is cached: without it every turn would walk all Chrome windows
    (~1.4s of observation each), which alone would cost 18 minutes over 100
    turns. A cached window is still verified -- the tab may have been closed
    or navigated away mid-run.
    """

    def _match(obs):
        if obs is None or not looks_like_chatgpt(obs):
            return False
        return _fallback or pin_token is None or _tree_has(obs, pin_token)

    hwnd = _CHATGPT_HWND["hwnd"]
    if hwnd and _activate(hwnd):
        time.sleep(0.4)
        obs = perception.observe()
        if _match(obs):
            return True, "cached", obs
        _CHATGPT_HWND["hwnd"] = None

    if focus_window("ChatGPT"):
        obs = perception.observe()
        if _match(obs):
            _CHATGPT_HWND["hwnd"] = win32gui.GetForegroundWindow()
            return True, "title", obs
    for cand in _chrome_hwnds():
        if not _activate(cand):
            continue
        time.sleep(0.5)
        obs = perception.observe()
        if _match(obs):
            _CHATGPT_HWND["hwnd"] = cand
            return True, f"hwnd={cand}", obs

    if pin_token and not _fallback:
        ok, how, obs = focus_chatgpt(perception, None, _fallback=True)
        if ok:
            return True, f"{how} [pin {pin_token} absent -> unpinned]", obs
        return False, f"no chatgpt window found (pin {pin_token})", None
    return False, "no chatgpt window found", None


def _input_box(nodes):
    """The DeepSeek composer as geometry, not as words.

    DeepSeek's input OCRs its placeholder to a single garbage character, so
    the text-anchor both finders rely on never matches. Three other bare
    inputs live in the tree, and size alone does not separate them all: the
    address bar (h=24) and the page container (w=1918) fail the box test,
    but markdown quote rows come back as type ``input`` with a 753x48 box
    that passes -- and clicking the first size-match in node order typed
    three of five prompts into the transcript instead of the composer. Two
    discriminators therefore: quotes carry a full sentence (text > 8 chars,
    while the composer's placeholder OCRs to one garbage character), and
    among survivors take the LOWEST box on the page -- quotes always sit
    above the input.
    """
    best = None
    for ntype, text, bbox in nodes:
        if ntype != "input" or not bbox or len(bbox) < 4:
            continue
        _x, y, w, h = bbox[:4]
        if not (400 <= w <= 900 and 40 <= h <= 160 and y > 300):
            continue
        if len((text or "").strip()) > 8:
            continue
        if best is None or y > best[1]:
            best = bbox
    return best


def find_composer(nodes):
    """Center of the chat input, anchored on its placeholder text."""
    if SITE == "deepseek":
        box = _input_box(nodes)
        if box:
            return box[0] + box[2] // 2, box[1] + box[3] // 2
        return None, None
    fallback = None
    for ntype, text, bbox in nodes:
        if not bbox or len(bbox) < 4:
            continue
        if "随便问" not in (text or "") and "有问题" not in (text or ""):
            continue
        if ntype == "input":
            return bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2
        if fallback is None:
            fallback = bbox
    if fallback:
        return fallback[0] + fallback[2] // 2, fallback[1] + fallback[3] // 2
    box = _input_box(nodes)
    if box:
        return box[0] + box[2] // 2, box[1] + box[3] // 2
    return None, None


def _layout(nodes):
    """(left, right, floor) of the transcript column.

    ChatGPT keeps base's text-anchored layout (composer placeholder words).
    DeepSeek must NOT call base: a reply line containing "有问题" is enough
    to make base treat that prose node as the composer, and floor then lands
    mid-conversation (806 instead of 1156), slicing the answer off. DeepSeek
    goes straight to the geometric input box.

    The horizontal padding is 60px, NOT ChatGPT's 400: DeepSeek renders a
    right-hand conversation OUTLINE panel (elided 175x17 entries, each
    carrying a message's full text) at x=2011 -- inside any padded band.
    Outline entries repeat every prompt in panel order, not transcript
    order, so anchoring on one put the band BELOW the real reply's opening
    lines (three replies came back mid-sentence) and below the trailing
    token badge (tagged stayed 0). Composer edges plus 60px still clear the
    sidebar (x<=574) and keep every transcript node (x>=1036).

    DeepSeek's floor is the TOP of the input box: its toggle row (深度思考 /
    智能搜索 / @) sits *below* the input, unlike ChatGPT's, so anchoring the
    floor there keeps those labels out of the band the same way ChatGPT's
    row-top floor keeps its +/思考 buttons out.
    """
    if SITE != "deepseek":
        left, right, floor = base._layout(nodes)
        if left is not None:
            return left, right, floor
    box = _input_box(nodes)
    if not box:
        return None, None, None
    x, w = box[0], box[2]
    return max(0, x - 60), x + w + 60, box[1]


def _is_our_message(text, tok):
    """Is this node the message WE sent for turn ``tok``, not its reply?

    Our prompts always BEGIN with the token (``R201 先聊聊旅行吧...``), the
    reply only APPENDS it (``...编号`` becomes ``成都。R201``), because the
    thread opener asks for that convention. Position therefore decides, not
    wording: the earlier rule matched instruction keywords after the token
    ("请用/回答"), which anchor hunting cannot survive once the chat turns
    into natural follow-ups like "为什么推荐成都".

    ``not endswith`` guards the one failure mode: a model that echoes the
    token at the START of its answer must not be taken for our own message,
    or the anchor jumps onto the reply and the band below it reads the next
    block (ads included) instead of the answer.
    """
    t = (text or "").strip()
    if not t.startswith(tok):
        return False
    return not t.endswith(tok)


_EXTRA_NOISE = re.compile(
    r"Monogram|UiPath|Applied A[I1] studio|copilots engineered|My Workspace"
    # DeepSeek's streaming thinking header lands between our message and the
    # answer when the R1 toggle is on; anchored so a reply that merely
    # discusses 深度思考 mid-sentence is not dropped as noise.
    r"|^已深度思考|^正在思考"
    # DeepSeek's copy button OCRs to a bare 'C' right after the token badge,
    # which would otherwise end every tagged reply with a stray letter.
    r"|^C$"
    # Same class of glyph: a standalone letter/digit node (OCR of a toggle or
    # collapsed-row icon) prefixed the reply head as 'Q R340 有修正…'. A real
    # reply line is always a full sentence, never one alphanumeric character.
    r"|^[A-Za-z0-9]$",
    re.I,
)


def _is_noise(text):
    return base._is_ui_noise(text) or bool(_EXTRA_NOISE.search(text or ""))


def _squash(text):
    """Whitespace-free form, for 'is this slice of what we sent?' checks.

    Whitespace differs between the prompt we typed and the node text (wrap
    points, OCR spacing), so a verbatim comparison must normalize first.
    """
    return re.sub(r"\s+", "", text or "")


def _reply_pieces(nodes, own_tokens, stop_token=None, prompt=None):
    """Ordered reply pieces from ONE observation: (pieces, why, meta, anchored).

    The site-specific part -- composer geometry, what counts as noise, how our
    token opening a node identifies OUR message -- is wired here; the ordering,
    band, dedup and identity logic is the reusable ``read_column`` primitive
    (mio_cua.perception.column), so those lessons are not trapped in this
    script. ``anchored`` is True when our own message was visible, i.e. this
    view holds the HEAD of the reply -- the scroll-stitch loop stops on it.

    ``prompt`` is the message we just sent: any node that is a verbatim
    (whitespace-free) slice of it is a wrapped continuation row of our own
    prompt, not answer text, and is skipped.
    """
    meta = {"nodes": len(nodes)}
    if not nodes:
        return [], "no scene nodes", meta, False

    left, right, floor = _layout(nodes)
    meta.update({"left": left, "right": right, "floor": floor})
    if left is None:
        return [], "composer not found", meta, False

    def _in_band(bbox):
        # Bounds the column and the browser chrome above it; the composer
        # floor is applied inside read_column so the token badge can be
        # excepted there (a DOM input box can overlap the last row).
        x, y = bbox[0], bbox[1]
        return left <= x <= right and y > 200

    read = column.read_column(
        nodes,
        tokens=list(own_tokens),
        in_band=_in_band,
        is_identity=_is_our_message,
        is_noise=_is_noise,
        stop_token=stop_token,
        prompt=prompt,
        floor=floor,
    )
    meta["user_y"] = read.boundary_y
    meta["anchored"] = read.anchored
    if not read.pieces:
        note = "" if read.anchored else f", fallback band (top={read.boundary_y})"
        return [], f"no prose below turn anchor (y={read.boundary_y}){note}", meta, read.anchored
    meta["reply_y"] = read.pieces[0][0]
    meta["pieces"] = len(read.pieces)
    note = "" if read.anchored else f", fallback band (top={read.meta['fallback_top']})"
    why = (
        f"{len(read.pieces)} node(s) below turn anchor y={read.boundary_y}{note}"
    )
    return read.pieces, why, meta, read.anchored



def extract_last_reply(obs, own_tokens, stop_token=None, prompt=None):
    """Single-view reply text -- the thin wrapper over ``_reply_pieces``.

    Kept as the public entry point (tests and the smoke probes use it); the
    full, scroll-stitched read lives in ``sweep_reply``.
    """
    pieces, why, meta, _anchored = _reply_pieces(
        base._node_tuples(obs), own_tokens, stop_token, prompt
    )
    if not pieces:
        return "", why, meta
    return " ".join(p[2] for p in pieces), why, meta


def _stitch_lines(acc, lines):
    """Prepend the non-overlapping head of ``lines`` to ``acc`` (see column)."""
    return column.stitch_lines(acc, lines)


def sweep_reply(pc, perception, own_tokens, stop_token=None, prompt=None,
                max_views=8):
    """Full reply text, stitched across scroll positions.

    The transcript viewport is ~900px, so an answer taller than that (the
    bullet-heavy ones are) is only PARTLY in the UIA tree, and DeepSeek does
    not follow the streaming tail -- a single observation captured the head and
    silently lost the rest plus the token badge (scale run: 13/20 turns read
    tagged=0 with visibly truncated tails). Read the end first, then page up
    collecting views until our own message comes into view (``anchored``) or
    the view stops changing, and stitch them by overlap.
    """
    obs = perception.observe()
    nodes = base._node_tuples(obs)
    left, right, floor = _layout(nodes)
    if left is None:
        return "", "composer not found", False
    # Click the blank gutter so PageUp/PageDown drive the transcript, not the
    # composer: a click inside the message column could hit a link.
    pc.execute(Action("click", "click", {"x": max(0, left + 8), "y": 420}))
    time.sleep(0.3)
    for _ in range(12):
        pc.execute(Action("key", "key", {"keys": "pagedown"}))
    time.sleep(0.6)

    acc, anchored, last_lines = [], False, None
    for _ in range(max_views):
        nodes = base._node_tuples(perception.observe())
        pieces, _why, _meta, anchored = _reply_pieces(
            nodes, own_tokens, stop_token, prompt
        )
        lines = [p[2] for p in pieces]
        if lines:
            acc = _stitch_lines(acc, lines)
        if anchored or lines == last_lines:
            break
        last_lines = lines
        pc.execute(Action("key", "key", {"keys": "pageup"}))
        time.sleep(0.7)
    for _ in range(12):  # leave the page at the newest message again
        pc.execute(Action("key", "key", {"keys": "pagedown"}))
    return " ".join(acc), "sweep", anchored


def settle(pc, perception, token, pin=None, prompt=None,
           timeout_s=180.0, quiet_s=5.0, interval_s=2.0):
    """Poll until this turn's reply stops changing (mirrors base._settle).

    quiet_s=5 (was 3), timeout 180s (was 60): an untethered deep-discussion
    reply streams for a minute or more and pauses several seconds between
    paragraphs -- polling at 3s reports a stable half-finished answer, and
    the 120s used since the deep-thread work still timed out on four
    consecutive turns whose R1 thinking ran long.

    Every poll re-acquires the ChatGPT window first (same ``pin`` as the
    send). Reading whatever happens to be in front is what let a smoke run
    pick up this chat window's own text and report 411 "chars" of reply; if
    focus is lost we must reclaim it rather than measure another app.
    """
    best, why, best_obs, meta = "", "timeout", None, {}
    stable_since, last = None, None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        ok, how, obs = focus_chatgpt(perception, pin)
        if not ok or obs is None:
            why = f"focus: {how}"
            time.sleep(interval_s)
            continue
        text, w, m = extract_last_reply(obs, [token], stop_token=pin, prompt=prompt)
        if text and text == last:
            if stable_since and time.time() - stable_since >= quiet_s:
                # A reply taller than the viewport was only partly in the tree
                # (see sweep_reply); read the whole thing before returning.
                full, _swhy, _anch = sweep_reply(
                    pc, perception, [token], stop_token=pin, prompt=prompt
                )
                # Only trust the sweep if it read at least as much as the
                # single view did; a botched stitch must not shrink the reply.
                if full and base._char_count(full) >= base._char_count(text):
                    text = full
                return text, w, obs, True, m
        else:
            stable_since = time.time() if text else None
        last, best, best_obs, best_why, meta = text, text, obs, w, m
        why = best_why
        time.sleep(interval_s)
    return best, why, best_obs, False, meta


def _toast_hint(obs):
    """Surface a visible failure toast, so a dropped send is diagnosable."""
    texts = [(t or "") for _, t, _ in base._node_tuples(obs)]
    for kw in ("频繁", "稍后", "上限", "限制", "失败", "重试", "太多", "排队"):
        if any(kw in t for t in texts):
            return kw
    return ""


def _sent_seen(obs, token):
    """True when our message exists outside the composer.

    ``_tree_has`` alone was fooled by DeepSeek: an Enter that did not send
    leaves the full draft in the input box, and the token still reads True
    there 2s later -- a false success that only surfaced as 'current prompt
    not in transcript' a full settle later. Delivery proof must therefore be
    structural: an ``input`` node is ALWAYS the composer (or the address bar
    or a markdown quote), never a delivered message, so it is skipped; a real
    message is a bubble inside the transcript band or, when the
    bottom-anchored scroll has pushed it out, an outline entry at x > right.
    With no composer found (left is None) nothing can be proven, so we fail
    rather than claim success.
    """
    nodes = base._node_tuples(obs)
    left, right, floor = _layout(nodes)
    if left is None:
        return False
    for ntype, text, bbox in nodes:
        if ntype in ("group", "input") or not bbox or len(bbox) < 4:
            continue
        x, y = bbox[0], bbox[1]
        if left <= x <= right and (floor is None or y < floor):
            if _is_our_message(text, token):
                return True
        elif x > right and (text or "").strip().startswith(token):
            return True
    return False


def send_turn(pc, perception, obs, prompt, token):
    """Type the prompt and confirm it actually reached the transcript.

    Two of five sends in the previous run vanished without a word -- the
    click landed on a look-alike box or Enter raced the render -- and
    ``send_turn`` still reported success; the loss only surfaced later as
    'current prompt not in transcript', indistinguishable from a network
    fault. So re-read the page ~2s after Enter: if our own token is not in
    the tree, re-acquire FRESH coordinates (the box may have moved while
    streaming) and try once more.
    """
    toast = ""
    for attempt in (1, 2):
        cx, cy = find_composer(base._node_tuples(obs))
        if cx is None:
            # A freshly opened page can be read one beat too early: the hero
            # composer is not in the tree yet and the whole turn is lost to
            # "composer not found" (turn 341 of the scale run). Re-focus and
            # re-read once before giving up.
            if attempt == 1:
                time.sleep(2.0)
                ok, _how, fresh = focus_chatgpt(perception, None)
                if ok and fresh is not None:
                    obs = fresh
                    continue
            return False, "composer not found"
        pc.execute(Action("click", "click", {"x": cx, "y": cy}))
        time.sleep(0.4)
        pc.execute(Action("clear", "key", {"keys": "ctrl+a"}))
        time.sleep(0.2)
        pc.execute(Action("type", "type", {"text": prompt}))
        time.sleep(0.4)
        pc.execute(Action("enter", "key", {"keys": "enter"}))
        time.sleep(2.0)
        ok, _how, obs2 = focus_chatgpt(perception, None)
        if ok and obs2 is not None and _sent_seen(obs2, token):
            return True, ""
        if obs2 is not None:
            toast = _toast_hint(obs2)
            obs = obs2
        if attempt == 1:
            time.sleep(2.0)
    suffix = f" ({toast} toast)" if toast else ""
    return False, f"send not delivered{suffix}"


def _save(out_path, results, counts, turns, limit, resume_from):
    """Write the report after EVERY turn.

    A 100-turn run takes ~35 min; losing it all to a crash at turn 97 would
    waste the whole session, so the partial report doubles as a checkpoint.
    """
    done = len(results)
    report = {
        "scenario": f"{SITE}_multiturn",
        "turns_requested": turns,
        "turns_run": done,
        "resume_from": resume_from,
        "limit_chars": limit,
        "summary": {
            **{k: v for k, v in counts.items()},
            "non_empty_rate": round(counts["non_empty"] / done, 3) if done else 0,
            "tagged_rate": round(counts["tagged"] / done, 3) if done else 0,
            "under_limit_rate": round(counts["under_limit"] / done, 3) if done else 0,
            "stable_rate": round(counts["stable"] / done, 3) if done else 0,
        },
        "why_counts": {},
        "results": results,
    }
    for r in results:
        w = r.get("why") or r.get("error") or "unknown"
        report["why_counts"][w] = report["why_counts"].get(w, 0) + 1
    Path(out_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def run(turns, limit, out_path, resume_from=1):
    pc = InputController()
    perception = Perception()
    results = []
    counts = {"non_empty": 0, "tagged": 0, "under_limit": 0, "stable": 0}

    for k in range(resume_from, resume_from + turns):
        tok = token_of(k)
        prompt = prompt_for(k)
        row = {"turn": k, "token": tok, "prompt": prompt}
        t0 = time.time()
        # The previous turn's token pins us to OUR conversation: two Chrome
        # windows hold different chatgpt.com chats, and content beats domain.
        pin = None if k == 1 else token_of(k - 1)
        try:
            ok, how, obs = focus_chatgpt(perception, pin)
            row["focus"] = how
            if not ok or obs is None:
                row.update(why=how, error="focus failed")
                results.append(row)
                print(f"[{k:03d}] FOCUS FAILED: {how}", flush=True)
                continue

            sent, why = send_turn(pc, perception, obs, prompt, tok)
            if not sent:
                row.update(why=why, error=why)
                results.append(row)
                print(f"[{k:03d}] SEND FAILED: {why}", flush=True)
                continue

            time.sleep(2.0)
            text, why, obs2, stable, meta = settle(pc, perception, tok, pin, prompt=prompt)
            chars = base._char_count(text)
            tagged = tok in text
            under = bool(text) and chars <= limit
            row.update(
                text=text, chars=chars, why=why, stable=stable, tagged=tagged,
                under_limit=under, duration_s=round(time.time() - t0, 1), **meta,
            )
            counts["non_empty"] += bool(text)
            counts["tagged"] += tagged
            counts["under_limit"] += under
            counts["stable"] += stable
            flag = "OK " if (tagged and under) else "!! "
            print(
                f"[{k:03d}] {flag}chars={chars:3d} stable={int(stable)} "
                f"tagged={int(tagged)} under={int(under)} "
                f"user_y={meta.get('user_y')} reply_y={meta.get('reply_y')} "
                f"floor={meta.get('floor')} | {why} | {text[:70]!r}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - one bad turn must not kill the run
            row.update(error=f"{type(exc).__name__}: {exc}", why="exception")
            print(f"[{k:03d}] EXCEPTION: {type(exc).__name__}: {exc}", flush=True)
        results.append(row)
        _save(out_path, results, counts, turns, limit, resume_from)

    done = len(results)
    report = _save(out_path, results, counts, turns, limit, resume_from)

    print("\n" + "=" * 60)
    print(f"turns run: {done}/{turns}")
    for k, v in counts.items():
        print(f"  {k:12s} {v:4d}  ({v / done:.0%})" if done else f"  {k}: 0")
    print("why:", report["why_counts"])
    print(f"report: {out_path}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=100)
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--out", default=str(TRACE_DIR / "multiturn_report.json"))
    ap.add_argument("--from", dest="resume_from", type=int, default=1)
    ap.add_argument(
        "--site",
        choices=("chatgpt", "deepseek"),
        default="chatgpt",
        help="which chat site to drive; recognition/focus/layout all follow it",
    )
    ap.add_argument(
        "--prompts-file",
        default="",
        help="one message per line; overrides the THREADS rotation, "
        "indexed relative to --from (e.g. a 5-round deep discussion)",
    )
    a = ap.parse_args()
    SITE = a.site
    _CHATGPT_HWND["hwnd"] = None
    if a.prompts_file:
        _PROMPTS = [
            ln.strip()
            for ln in Path(a.prompts_file).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        _PROMPT_BASE = a.resume_from
        print(f"loaded {len(_PROMPTS)} prompts from {a.prompts_file}", flush=True)
    run(a.turns, a.limit, a.out, a.resume_from)
