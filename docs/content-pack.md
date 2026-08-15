# mio-cua 内容营销素材包

> 原则：**把代码拆成内容**——一个项目至少拆成 10 篇博客 / 20 条推文 / 5 个视频 / 3 个案例。
> 所有草稿均为"开箱即用"，英文稿可直接发 HN / Reddit / dev.to / Medium / X；中文稿发掘金 / 思否 / 微信公众号 / B 站。
> 仓库：`https://github.com/mldlbs/mio-cua`

---

## A. Hacker News（Show HN，D4 09:00 UTC 发）

**标题（三选一）：**
1. `Show HN: I gave my AI eyes instead of APIs — a Windows computer-use agent`
2. `Show HN: mio-cua — operate any Windows app by seeing the screen (no API needed)`
3. `Show HN: A computer-use agent that runs cross-app tasks on Windows with OCR + UIA scene graph`

**正文（讲故事，不写广告）：**

```
I kept hitting the same wall with agent frameworks: every automation needed an API.

But most software doesn't have one. Banks, ERPs, government systems, old desktop
apps — they're designed for humans. Eyes on screen, hand on mouse.

So I built the opposite: instead of writing an interface for the AI, I gave it eyes.
It OCRs the screen, builds a "scene graph" (every UI element is a node with text/type/
state/bbox + spatial relations), and the LLM picks from VERIFIED action candidates
instead of guessing coordinates.

Why not just UIA/accessibility? Because it breaks on everything that isn't a standard
widget, and web pages are a black box. So web is done purely visually too — regions
layout + OmniParser, no DOM, no extension.

What works today (real Windows 11, cheap model deepseek-v4-flash):
- Notepad: open, type, save
- Calculator: 123*456=56088
- Cross-app: read file → calculator sum → save result
- Web: click and type on a page with zero DOM access

Safety is the boring 50%: F9 emergency stop, screenshot-per-step audit trail,
--dry-run, and an isolated virtual-desktop mode so it never touches your real desktop
while testing.

Would love feedback on the scene-graph approach — I think grounding actions in
perception-validated candidates is the right direction, but I'm sure there are holes.

https://github.com/mldlbs/mio-cua
```

---

## B. Reddit（r/LocalLLaMA + r/opensource + r/Python，D4 发）

**标题（问题先行，不直接给链接）：**
- `I made an AI agent that controls Windows apps by looking at the screen (OCR + UIA scene graph)`

**正文（先讲问题，最后给链接）：**

```
I've been trying to get an LLM to operate real desktop software for a while.

The existing approaches all hit the same wall:
- UIA/accessibility APIs only work on well-behaved widgets, and web is a black box
- Traditional RPA means hand-dragging flows that break the moment the UI changes
- Most agent frameworks assume you can call an API — but banks/ERP/legacy apps
  simply don't have one

My take: don't give the software an API, give the AI eyes. It reads the screen
(OCR + UIA fused into a scene graph), and the model picks from action candidates
that perception already validated — it never guesses coordinates.

It's a Python SDK + CLI + MCP server (so Claude/Cursor/ChatGPT can control the
desktop too). Verified end-to-end on Windows 11: calculator, notepad, explorer,
cross-app (read file → sum in calculator → save), and web with zero DOM access.

Demo + 5 verified scenarios here:
https://github.com/mldlbs/mio-cua
```

**评论区留白**：提前准备 2–3 条自答——"为什么不用 Playwright？""怎么保证安全？""和 UI-TARS 有什么区别？"（对应答案见 E 节）。

---

## C. 推文线程（X / Twitter，D4–D7 每天一条）

**Thread 1（Day 1，发布日）— 讲理念：**
```
1/ 大部分软件没有 API，但它们每天都在被人操作——人看屏幕、点鼠标。
2/ 所以我不给 AI 写接口，给它一双眼睛。
3/ mio-cua 用 OCR + UIA 融合成"场景图"，LLM 从感知层验证过的动作候选中选择，不猜坐标。
4/ 网页也走纯视觉：Regions + OmniParser，不需要 DOM、不需要插件。
5/ 真实 Windows 11 已跑通 5 个场景，F9 急停 + 逐步截图留痕。
6/ 开箱即用：pip install mio-cua → 说一句话，它干活。github.com/mldlbs/mio-cua
```

**Thread 2（Day 2）— 讲技术痛点：**
```
1/ Accessibility API 的坑：非标准控件拿不到、网页是黑盒、UI 一变就失效。
2/ 所以感知层把 OCR + UIA 融成一张场景图：每个 UI 对象是 Node（文本/类型/状态/坐标/关系）。
3/ LLM 只从已验证的候选动作里选 → 动作永远 grounded，不猜。
4/ 一动作一感知：每步重新看屏幕再决策，绝不基于过期场景执行。
```

**Thread 3（Day 3）— 跨应用 demo：**
```
1/ 一条指令，三个应用：读文件 → 计算器求和 → 保存结果。
2/ "读取 smoke_numbers.txt（12/34/56），用计算器求和（102），保存到新文件。"
3/ 全程 AI 自己看屏幕、自己点、自己验证显示区 0→7 变化。
4/ 这就是新一代 RPA：你说一句，它自己做完。
```

**Thread 4（Day 4）— 安全 + 信任：**
```
1/ 让 AI 操作真实桌面前，安全是另一半工作量。
2/ F9 急停、步数上限、每步截图留痕、--dry-run 只打印计划。
3/ 测试隔离在虚拟桌面，不碰你的主桌面。
4/ 文件移动拒绝覆盖已有文件。跑之前先冒烟测一次。
```

**Thread 5（Day 5–6）— MCP 生态：**
```
1/ mio-cua 还是个 MCP server：Claude / Cursor / ChatGPT 装上就能控制你的 Windows 桌面。
2/ 27 个工具：文件、窗口、点击、输入、剪贴板、进程、虚拟桌面……
3/ 把桌面操作能力给任何 MCP 客户端 = AI 的边界从"调接口"变成"操作任何软件"。
```

---

## D. 博客选题表（10 篇）

| # | 中/英 | 标题 | 核心钩子 | 渠道 | 状态 |
|---|---|---|---|---|---|
| 1 | 中 | 别给 AI 写接口，给它一双眼睛 | 理念 | 掘金/思否 | ✅ `blog/mio-cua-intro.md` |
| 2 | 英 | Why accessibility APIs aren't enough for desktop agents | 技术痛点 | dev.to/HN | ✅ `blog/why-accessibility-apis-arent-enough.md` |
| 3 | 英 | Building a scene graph: fusing OCR + UIA for grounded action selection | 架构 | dev.to/Medium | ✅ `blog/building-a-scene-graph.md` |
| 4 | 英 | Pure-vision web automation: no DOM, no extensions | 创新点 | dev.to | ✅ `blog/pure-vision-web-automation.md` |
| 5 | 中 | 跨应用 RPA：AI 怎么自己读文件→求和→保存 | 场景 | 掘金 | ✅ `blog/crossapp-rpa.md` |
| 6 | 英 | Safe computer-use agents: emergency stop, audit trails, virtual desktops | 安全 | dev.to | ✅ `blog/safe-computer-use-agents.md` |
| 7 | 中 | 用便宜的 deepseek-v4-flash 也能跑通桌面 Agent | 成本 | 掘金 | ✅ `blog/cheap-model-desktop-agent.md` |
| 8 | 英 | mio-cua as an MCP server: giving Claude/Cursor hands on Windows | MCP 生态 | dev.to/HN | ✅ `blog/mio-cua-as-mcp-server.md` |
| 9 | 中 | 我把 AI 接到真实 Windows 桌面的踩坑记录（6 个工程 bug） | 复盘 | 思否 | ✅ `blog/6-bugs-on-real-desktop.md` |
| 10 | 英 | From 0 to cross-app: the 5 scenarios we verify on every commit | 质量/CI | dev.to | ✅ `blog/5-scenarios-verified.md` |

> 每篇博客 → 拆 1 条推文 + 1 个社区帖，形成飞轮。

---

## E. 常见问题 / 评论区弹药

| 问题 | 答案要点 |
|---|---|
| 为什么不用 Playwright / Selenium？ | 网页只是场景之一；桌面原生应用没有 DOM，且很多网站禁自动化。纯视觉覆盖两者。 |
| 和 UI-TARS / OpenInterpreter 有什么区别？ | UI-TARS 是模型+框架；mio-cua 是开箱即用 SDK+CLI+MCP，感知层用 OCR+UIA 融合而非纯视觉，便宜模型即可跑。 |
| 怎么保证安全？ | F9 急停、步数/超时上限、每步截图留痕、--dry-run、文件移动拒绝覆盖、虚拟桌面隔离。 |
| 只支持 Windows？ | 当前是（pywin32/pywinauto），Roadmap 有 Linux/macOS vision-only 回退。 |
| 需要贵模型吗？ | 不需要，deepseek-v4-flash 即可跑通全部 5 场景。 |
| 对中文/复杂 UI 支持？ | 中文界面实测可跑（OCR 支持中文），复杂控件走 UIA + OCR 双通道融合。 |

---

## F. 视频脚本（5 条）

**Video 1（发布日，英文，≤90s）— "Give your AI eyes, not APIs"**
```
[0-10s] 真人画外音 + marquee 封面："Most software has no API. But it gets used every day."
[10-30s] 屏幕录制：打开计算器，"mio-cua run 打开计算器，计算 3*4" → 光标自动点击
[30-60s] 切到 overlay 视角：OCR 框 + 场景图节点 + LLM 决策日志
[60-90s] 结尾："Star it, or give it a job: github.com/mldlbs/mio-cua"
```

**Video 2（D8，英文）— Cross-app demo 完整流程（2 分钟）**
**Video 3（D10，英文）— "How the scene graph grounds LLM actions"（架构讲解 + 屏幕录制）**
**Video 4（D15，中文 B 站）— 别给 AI 写接口，给它一双眼睛（演示向）**
**Video 5（D20，英文）— v0.2 新特性发布 demo**

---

## G. Product Hunt（D16 launch）

- **Name**：mio-cua — Computer-Use Agent for Windows
- **Tagline**：Give your AI eyes, not APIs. It sees your screen and operates any app.
- **Description**：AI desktop automation agent for Windows. Scene-graph perception (OCR+UIA), pure-vision web automation, MCP server included. Works with cheap models. F9 emergency stop + screenshot-per-step audit trail.
- **First comment（由你发）**：讲"为什么 Accessibility API 不够 + 下一步 roadmap"，引导评论互动。

---

## H. 分发排期总表（与 growth-plan 对齐）

| 日 | 渠道 | 物料 |
|---|---|---|
| D4 | HN / Reddit / 掘金 / X Thread1 | A/B/C1 稿 |
| D5 | dev.to+Medium / 思否 | D2/D5/D7 稿 + 教程 |
| D6 | X Thread2/3 / B 站预热 | C2/C3 + Video1 剪辑 |
| D7 | X Thread4/5 / GitHub Discussions 开启 | C4/C5 + 社区帖 |
| D8–14 | 博客连载 + 视频 | D3/D4/D6/D8/D9 + Video2/3 |
| D15–21 | Product Hunt / 案例 / B站 | G + 案例征集 + Video4 |
| D22–30 | v0.2 发布 + 深度架构文 | D10 + Video5 + 庆祝公告 |
