# mio-cua 0→1000 Star 30 天增长方案

> 目标：30 天内从 ~0 到 1000 Star。原则：**50% 产品 + 50% 分发**，Star Velocity 比总量重要。
> 当前资产盘点：README 已按转化结构重写、promo 图已齐（marquee/small/vertical）、博客 `blog/mio-cua-intro.md` 已写。缺：Demo GIF、PyPI 发布、LICENSE、release tag、英文内容稿。

---

## 阶段总览

| 阶段 | 天数 | 目标 | 核心动作 |
|---|---|---|---|
| D1–3 | 蓄水 | 产品可发布 | GIF + LICENSE + PyPI + release tag + 英文教程 |
| D4–7 | 冷启动 | 0–100 Star | 第一波内容（HN/Reddit/掘金）72h 集中爆发 |
| D8–14 | 加速 | 100–300 Star | 博客连载 + 社区互动 + 二次传播 |
| D15–21 | 规模化 | 300–600 Star | 视频 + 案例 + Product Hunt + 转介绍 |
| D22–30 | 冲线 | 600–1000 Star | 里程碑式发布 v0.2 + 压舱内容 + 维持节奏 |

---

## D1–3：蓄水（发布前必做）

- [ ] **Demo GIF**：录一个 30s 内 GIF——用 vdesk 隔离跑 calculator 或 web 场景，配 `promo/promo-marquee.png` 当封面。README 已有 TODO 占位，替换即可。GitHub 首页必须 3 秒内看懂。
- [ ] **LICENSE**：补 MIT（`docs/seo-checklist.md` 也标了，信任门槛）。
- [ ] **PyPI 发布**：`python -m build && twine upload` → README 里 `pip install -e .` 换成 `pip install mio-cua`（信任信号 + 可复制安装命令）。
- [ ] **release tag**：`git tag v0.1.5` + release notes（GitHub 索引 + 公告素材）。
- [ ] **英文快速上手教程**：GitHub Wiki 或 docs/ 放一篇英文 step-by-step（配截图），SEO 二次入口，同时是 HN/Reddit 的正文素材。
- [ ] 整理证据包：5 个场景 PASS 的日志 + 截图，存 `docs/evidence/`。

## D4–7：冷启动（72h 集中引流）

**核心：同一天尽量同步发，制造短时间 spike（Trending 看 velocity）。**

| 渠道 | 时间 | 物料（见 content-pack） |
|---|---|---|
| Hacker News `Show HN` | D4 09:00 UTC | HN 帖草稿（英文） |
| Reddit r/LocalLLaMA + r/opensource | D4 | Reddit 正文草稿 |
| 掘金 | D4 晚 | 《别给 AI 写接口，给它一双眼睛》正文 |
| X / Twitter | D4–7 每天 | 推文线程草稿 |
| dev.to / Medium | D5 | 英文教程长文 |
| 思否/CSDN | D6 | 中文教程转载 |

**冷启动技巧：**
- HN 别用营销口吻，讲技术决策（为什么 UIA 不够 → OCR+UIA 融合 Scene Graph；为什么 web 走纯视觉）。
- Reddit 先讲问题再给链接（正文草稿已按此结构）。
- 每条渠道指向同一个落地点：README → 一屏内完成"看懂 + 安装 + 试跑"。

## D8–14：加速

- [ ] 博客连载（英文 2 篇 + 中文 2 篇），标题即搜索词，见 content-pack 选题表。
- [ ] 每个渠道回评论区互动 3 天：HN/Reddit 前 48h 的讨论度决定曝光。
- [ ] 把 Star 数/反馈回灌 README（社会证明）：加一行 "⭐ 800+ · 已在真实 Windows 11 验证 5 场景"。
- [ ] 找 3 个开源/KOL 互推（社区而非"互点 star"）：在 r/Python、Discord、微信群发使用体验，请真实用户贡献 issue/PR。
- [ ] 用 `docs/seo-checklist.md` 过一遍 Topics 补齐（一次全配上）。

## D15–21：规模化

- [ ] **视频**：1 条英文 demo（配字幕）发 YouTube（标题含 `AI desktop automation agent Windows`）+ 1 条中文发 B 站。
- [ ] **Product Hunt** launch（工具类/AI 类合适）：准备 tagline = README 一句话；发布当天让支持者集中点赞。
- [ ] **案例收集**：邀请 3 个真实用户写下使用场景（写入 README "Who's using"），形成飞轮证据。
- [ ] 二波内容：把 5 个场景拆成 5 篇"如何让 AI 操作 X"短文（notepad/calculator/explorer/crossapp/web）。
- [ ] 与同类项目互动：在 GitHub Discussions / issues 里给同领域项目（如 UI-TARS、OpenInterpreter、自用 RPA）提有质量 issue，产生关注回流。

## D22–30：冲线

- [ ] **v0.2 milestone 发布**：挑一个杀手级特性（如"截图自动生成 YAML 场景"或"多步 planner 重构"），发 release + 全渠道宣告，制造第二个 spike。
- [ ] 压舱内容：1 篇深度架构文（Scene Graph 设计）发 HN「Ask/Look what I built」+ 掘金/思否，把专业度拉满。
- [ ] 转介绍：README 加 `Share` 按钮文案 + 微信群/朋友圈引导。
- [ ] 复盘：哪个渠道转化最高 → 最后一周加倍投放。
- [ ] 1000 Star 后立刻发庆祝公告（二次传播），并转向"维护 + 持续内容"长线运营。

---

## 防雷

- ❌ 买 Star / Star-for-Star / 刷 Trending——检测异常增长，一票否决。
- ❌ 内容全发"v0.x 发布了"这种自嗨标题——必须讲问题和架构。
- ❌ 冷启动期渠道铺开但 README 没 GIF / 装不上——转化全废，D1–3 蓄水是硬门槛。

## 渠道转化预期（供校准）

| 渠道 | 单次爆发量级 | 转化到 Star 的杠杆 |
|---|---|---|
| HN Show HN | 50–300+ 点击看 | 高（技术人群体） |
| Reddit | 50–500 | 中高（垂直社区） |
| 掘金/思否 | 1000–5000 阅读 | 中（中文用户） |
| Product Hunt | 100–500 浏览 | 中（有工具属性） |
| X 线程 | 500–5000 曝光 | 低中（需要 KOL 转发） |
