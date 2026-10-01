"""Acceptance-extraction tests for the ChatGPT chat scenario (FR-1).

The scenario's PASS/FAIL is decided by `_extract_reply`, not by the agent, so
these rules are load-bearing:

  * a page that has never been sent anything must NOT look like a valid reply
    (the fresh-chat greeting "你好，Meng。准备好开始了吗？" is only 16 chars and
    would otherwise satisfy a <=50 rule all by itself)
  * a reply measured mid-stream is shorter than the finished one, so the
    scenario must settle first -- these tests cover the extraction itself
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "trace"))

import record_chatgpt_chat as scenario  # noqa: E402

PANEL = [682, 0, 1248, 1560]          # centre panel, from recon group node
COMPOSER = [1033, 711, 153, 26]       # "有问题，随便问"
GREETING = [1222, 631, 348, 35]       # "你好，Meng。准备好开始了吗？"


def node(text, bbox, type_="text", nid=0):
    return {"id": nid, "type": type_, "text": text, "semantic": text, "bbox": bbox}


def obs(nodes):
    return SimpleNamespace(scene_nodes=nodes, active_window="ChatGPT - Google Chrome")


def base_page(prompt=""):
    """The recon page: chrome-free centre panel, greeting, composer row."""
    nodes = [
        {"id": 1, "type": "group", "text": "", "semantic": "", "bbox": PANEL},
        node("A智能决策中心", [35, 1, 117, 24]),
        node("ChatGPT-任务管理", [514, 2, 139, 22]),
        node("你好，Meng。准备好开始了吗？", GREETING, nid=29),
    ]
    if prompt:
        nodes.append(node(prompt, [1100, 650, 320, 26], nid=90))
    nodes.append(node("十有问题，随便问", COMPOSER, nid=31))
    nodes.append(node("任务有操作需要您的确认，请点击查看", [2184, 1495, 264, 27], nid=58))
    return nodes


def test_fresh_chat_page_is_never_a_reply():
    """Nothing sent yet -> no answer, whatever the greeting says."""
    text, why = scenario._extract_reply(obs(base_page()))
    assert text == ""
    assert "prompt not in transcript" in why


def test_greeting_above_the_prompt_is_not_the_reply():
    """The reply is everything below our message, so the greeting is skipped."""
    nodes = base_page(scenario.PROMPT)
    nodes.append(node("我是由 OpenAI 训练的语言模型，很高兴认识你。", [1100, 672, 380, 26], nid=91))
    text, why = scenario._extract_reply(obs(nodes))
    assert "准备好开始" not in text
    assert "语言模型" in text


def test_reply_collects_multiple_ocr_lines_in_order():
    """A wrapped reply arrives as several nodes; they must concatenate by y."""
    nodes = base_page(scenario.PROMPT)
    nodes.append(node("我是一个人工智能助手，", [1100, 672, 300, 26], nid=91))
    nodes.append(node("可以回答各种问题，", [1100, 688, 300, 26], nid=92))
    nodes.append(node("帮助你完成任务。", [1100, 704, 300, 26], nid=93))
    text, _ = scenario._extract_reply(obs(nodes))
    assert text == "我是一个人工智能助手， 可以回答各种问题， 帮助你完成任务。"
    assert scenario._char_count(text) == 28


def test_prompt_present_but_still_streaming():
    """Sent, no text below it yet: not a pass, and not 'never sent' either."""
    text, why = scenario._extract_reply(obs(base_page(scenario.PROMPT)))
    assert text == ""
    assert "no reply yet" in why


def test_sidebar_and_popup_never_reach_the_transcript():
    """x outside the centre panel is the sidebar (x<682) or WorkBuddy (x>1930)."""
    nodes = base_page(scenario.PROMPT)
    nodes.append(node("我是一个人工智能助手。", [1100, 672, 300, 26], nid=91))
    nodes.append(node("深思考", [6, 252, 89, 27], nid=19))              # sidebar
    nodes.append(node("领取优惠", [86, 1509, 75, 23], nid=59))           # below composer
    text, _ = scenario._extract_reply(obs(nodes))
    assert text == "我是一个人工智能助手。"


def test_own_message_repeated_in_the_reply_is_dropped():
    nodes = base_page(scenario.PROMPT)
    nodes.append(node("你让我介绍我自己：" + scenario.PROMPT, [1100, 672, 380, 26], nid=91))
    nodes.append(node("我是人工智能。", [1100, 688, 300, 26], nid=92))
    text, _ = scenario._extract_reply(obs(nodes))
    assert text == "我是人工智能。"


def test_real_recon_capture_is_not_a_pass():
    """The recorded fresh-chat page must not be mistaken for an answer."""
    data = json.loads((ROOT / "trace" / "recon_chatgpt.json").read_text(encoding="utf-8"))
    text, why = scenario._extract_reply(obs(data["all_nodes"]))
    assert text == ""
    assert "prompt not in transcript" in why


def _uia_nodes():
    path = ROOT / "trace" / "recon_chatgpt_ui.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["all_nodes"]


def _strip_empty_state(nodes):
    """Drop the greeting block ChatGPT removes as soon as a message exists.

    It is three nodes -- a group, the greeting text and the `Meng` avatar
    button -- spread over y 776..807, so matching only the greeting's own
    text leaves the avatar behind to be counted as part of the answer.
    """
    return [n for n in nodes if not (760 <= n["bbox"][1] <= 820 and n["bbox"][0] >= 1000)]


def test_real_uia_capture_keeps_the_sidebar_out_of_the_reply():
    """Regression for the full-screen-group bug.

    Chrome's UIA tree reports a group spanning the whole window, so anchoring
    the transcript on the *largest* group made the panel bounds the entire
    screen -- and every sidebar history item was then read back as ChatGPT's
    reply. The sidebar's rows sit at y 614..946, x 355..594, i.e. squarely
    inside the band a real reply occupies.
    """
    nodes = _uia_nodes()
    if nodes is None:
        pytest.skip("UIA capture not present (run trace/check_foreground.py)")

    # Once a message exists ChatGPT drops the empty-state greeting.
    nodes = _strip_empty_state(nodes)
    nodes.append(node(scenario.PROMPT, [1200, 480, 320, 26], nid=900))
    nodes.append(node("我是人工智能助手。", [1200, 560, 320, 26], nid=901))

    text, why = scenario._extract_reply(obs(nodes))
    assert text == "我是人工智能助手。", f"leaked other page text: {why}: {text!r}"


def test_real_uia_capture_drops_the_composer_row_siblings():
    """`+`, 思考 and the mic sit ~8px ABOVE the input (y=849 vs y=853).

    Flooring the transcript at the input's top edge left them inside the
    answer band; the floor has to be the top of the whole composer row
    (the group at y=841).
    """
    nodes = _uia_nodes()
    if nodes is None:
        pytest.skip("UIA capture not present (run trace/check_foreground.py)")

    nodes = _strip_empty_state(nodes)
    nodes.append(node(scenario.PROMPT, [1200, 700, 320, 26], nid=900))
    nodes.append(node("我是人工智能助手。", [1200, 730, 320, 26], nid=901))

    text, why = scenario._extract_reply(obs(nodes))
    assert text == "我是人工智能助手。", f"composer row leaked: {why}: {text!r}"


def test_real_uia_capture_without_prompt_still_reports_missing():
    nodes = _uia_nodes()
    if nodes is None:
        pytest.skip("UIA capture not present (run trace/check_foreground.py)")
    text, why = scenario._extract_reply(obs(nodes))
    assert text == ""
    assert "prompt not in transcript" in why


def test_char_count_ignores_whitespace_but_not_glyphs():
    assert scenario._char_count("你好，世界") == 5
    assert scenario._char_count(" 你 好 \n 世界 ") == 4  # spaces stripped, glyphs kept
    assert scenario._char_count("") == 0
    assert scenario._char_count(None) == 0


@pytest.mark.parametrize(
    "text,expected",
    [
        (scenario.PROMPT, True),
        ("请严格用不超过50个字介绍你自己", True),
        ("介绍你自己", True),
        ("我是一个语言模型，可以介绍你自己吗", True),
        ("我是一个语言模型，可以回答问题", False),
    ],
)
def test_own_message_matching(text, expected):
    assert scenario._is_own_message(text) is expected


# ── The conversation as it actually looked ──────────────────────────────────
# Captured from trace_1790820277 (2026-10-01): control labels under our
# message (y=486), the answer (y=525), the answer's own labels (y=559), the
# Cartesia ad (y=621..721) and the disclaimer (y=1379). Counting every node
# below the prompt measured 222 chars against an answer of 36 -- the run was
# reported invalid purely because of that. Coordinates are the real ones, so
# the layout code is exercised too.
CONVERSATION = [
    ("复制消息", [1732, 486, 58, 22]),
    ("分享提示", [1764, 486, 58, 22]),
    ("编辑消息", [1796, 486, 58, 22]),
    ("我是GPT-5.6 Luna，擅长分析、推理、写作、编程与解决复杂问题。", [1060, 525, 700, 36]),
    ("复制回复", [1054, 559, 58, 22]),
    ("评价回复", [1086, 559, 58, 22]),
    ("分享", [1118, 559, 30, 22]),
    ("切换模型", [1150, 559, 58, 22]),
    ("更多操作", [1182, 559, 58, 22]),
    ("Find your", [1060, 621, 70, 22]),
    ("更多选项", [1456, 621, 58, 22]),
    ("Cartesia", [1194, 638, 58, 22]),
    ("广告", [1426, 639, 30, 22]),
    ("unique voice", [1066, 641, 90, 22]),
    ("One APl for Real-Time Voice", [1194, 663, 220, 22]),
    ("Speech generation, transcription, and", [1193, 683, 260, 22]),
    ("production voice agents, all through on...", [1193, 705, 300, 22]),
    ("CARTESIA", [1067, 721, 70, 22]),
    ("ChatGPT 也可能会犯错。请核查重要信息。", [1327, 1379, 240, 23]),
]

ANSWER = "我是GPT-5.6 Luna，擅长分析、推理、写作、编程与解决复杂问题。"


def _page(nodes, prompt=scenario.PROMPT):
    """`nodes` (text, bbox) plus our own message and the composer row.

    The composer's text must name it and its type must be input/group/button
    so that `floor` lifts to the top of the whole row (y=1411). That keeps the
    disclaimer at y=1379 *inside* the band, where it can be -- and must be --
    filtered out, rather than silently floored away.
    """
    ns = [node(t, b) for t, b in nodes]
    ns.append(node(prompt, [1100, 450, 320, 26], nid=900))
    ns.append(node("有问题，尽管问", [1100, 1411, 531, 26], type_="input", nid=901))
    return obs(ns)


def conversation_obs():
    return _page(CONVERSATION)


def test_real_conversation_yields_only_the_answer():
    """222 -> 36 chars: the regression that made a passing run look failed."""
    text, why = scenario._extract_reply(conversation_obs())
    assert scenario._char_count(text) == 35
    assert text == ANSWER
    assert "1 of 19 node(s)" in why


def test_chrome_never_counts_toward_the_limit():
    text, _ = scenario._extract_reply(conversation_obs())
    for noise in ("复制消息", "分享提示", "编辑消息", "复制回复", "评价回复",
                  "切换模型", "更多操作", "更多选项", "广告", "CARTESIA",
                  "unique voice", "Find your", "也可能会犯错"):
        assert noise not in text, noise
    assert len(text) <= scenario.MAX_REPLY_CHARS


def test_answer_followed_by_ad_without_button_row():
    """No button row in between: the ad itself must end the answer."""
    text, why = scenario._extract_reply(_page([
        ("好的，我是一名AI助手，很高兴为你服务。", [1060, 525, 500, 36]),
        ("CARTESIA", [1067, 621, 70, 22]),
    ]))
    assert text == "好的，我是一名AI助手，很高兴为你服务。", f"{why}: {text!r}"


def test_brief_answer_is_kept():
    """No length threshold: only chrome is filtered, so a short answer counts."""
    text, why = scenario._extract_reply(_page([
        ("我是一个AI模型，乐于助人。", [1060, 525, 400, 36]),
    ]))
    assert text == "我是一个AI模型，乐于助人。", f"{why}: {text!r}"


def test_ui_noise_labels():
    for s in ("复制消息", "分享提示", "编辑消息", "复制回复", "评价回复", "分享",
              "切换模型", "更多操作", "更多选项", "广告", "重新生成",
              "ChatGPT 也可能会犯错。请核查重要信息。",
              "CARTESIA", "unique voice", "Find your"):
        assert scenario._is_ui_noise(s) is True, s
    for s in (ANSWER, "我是一个AI模型，乐于助人。", "当然可以，我来介绍一下："):
        assert scenario._is_ui_noise(s) is False, s
