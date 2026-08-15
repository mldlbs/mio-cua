# GitHub SEO — mio-cua

SEO 目的：让项目在 GitHub 搜索、Google、Hacker News 被"搜得到"。仓库 URL 是 `https://github.com/mldlbs/mio-cua`（当前仓库名 `mio-cua` 尚可，但 Description / Topics 必须补）。

## 1. 仓库名（已在 github.com/mldlbs/mio-cua）

- 现状：`mio-cua`（`mio` 品牌 + `cua` = Computer-Use Agent，缩写对新手不友好）
- 可选改名（代价：旧 URL 失效，需 301 转发，MCP registry `server.json` / `pyproject.toml` name 同步改）：
  - `mio-cua`（推荐保留，品牌已注册 MCP Registry，SEO 靠 Description/Topics 兜底）
  - `desktop-agent`（泛，撞车多）
  - `mio-desktop-agent`（折中）
- **建议：不改名**，把力气花在 Description + Topics + README 首屏。

## 2. Description（GitHub 仓库设置 → About）

当前：`Mio Computer-Use Agent: Windows desktop automation AI agent (SDK + CLI)`

建议（搜得到的写法，< 80 字符 + 命中关键词）：

```
AI desktop automation agent for Windows — sees your screen, operates any app like a human. OCR + vision + MCP server.
```

备用：
```
Computer-use agent: control Windows apps with natural language. OCR + UIA scene graph, web without DOM, MCP server.
```

要求：含 `desktop automation` / `computer-use` / `Windows` / `agent` / `MCP` 高频词；首句即答案。

## 3. Topics（GitHub 仓库设置 → Topics，最多 20 个，全部小写）

```
desktop-automation
computer-use
ai-agent
llm-agent
windows
automation
rpa
ocr
computer-vision
agent-framework
mcp
mcp-server
claude
browser-automation
python
uiautomation
gui-automation
openai-compatible
scene-graph
visual-agents
```

勾选 `Include topics` 建议接受 GitHub 自动补全的前缀词。

## 4. README SEO 要素（已随重写覆盖）

- 首屏 Hero + 一句话定位（含 `computer-use agent` / `Windows` / `desktop automation` 关键词）
- H1 = `mio-cua`（仓库名）；H2 用语义化标题（`What is` / `Quick Start` / `Demo` / `Roadmap`）
- 链接用绝对仓库路径（`https://github.com/mldlbs/mio-cua`），避免相对链接在 fork 中失效
- 图片 alt 文本带关键词（如 `mio-cua computer-use agent screenshot`）

## 5. 其他一劳永逸项

- [ ] 补 `LICENSE`（MIT）——开源项目信任门槛
- [ ] GitHub 仓库 `About` 填官网/文档链接（后续 blog 可挂 `https://github.com/mldlbs/mio-cua` 的 wiki）
- [ ] 开 Discussions（流量承接 + 社区信号）
- [ ] 打 `v0.1.5` release tag，配 release notes（GitHub 会索引）
- [ ] 启用 GitHub Pages / Wiki 放一篇英文教程（SEO 二次入口）
- [ ] PyPI 发布后 `pip install mio-cua` 在 README 中替换 `pip install -e .`（信任信号）

## 6. 外部可发现性

- MCP Registry `server.json` 已配（`io.github.mldlbs/mio-cua`）——MCP 生态是新流量口
- Google:README 关键词 + PyPI + 后续博客/掘金/HN 外链共同提升排名
