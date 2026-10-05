# 用便宜的 deepseek-v4-flash 也能跑通桌面 Agent

> Draft for 掘金/思否. Repo: https://github.com/mldlbs/mio-cua

---

"桌面 Agent 不都是要 GPT-4o / 多模态旗舰模型吗？"——这是被问到最多的问题之一。答案分两层：**感知层把世界结构化好，模型只做决策**，所以推理模型不用太贵。

mio-cua 五个端到端场景全部用 **deepseek-v4-flash** 跑通（2026-08-08 全绿终验），零代码改动。这篇聊聊"怎么做到让便宜模型也能干活"。

## 1. 模型需要决定的事，被感知层大幅简化了

一个 Agent 的每一步其实要回答三类问题：

| 问题 | 传统做法（模型硬扛） | mio-cua 的做法 |
|---|---|---|
| 屏幕上有什么？ | 模型自己看截图，逐个找按钮 | 感知层 OCR+UIA 融合成场景图，编号框一一对应 |
| 能点哪些？ | 模型自行推断坐标 | 感知层给出**已验证的动作候选**（affordances） |
| 点对了吗？ | 模型再次读屏脑补 | Scene Diff 检查显示值 `0→7` 是否真的变了 |

模型要做的只剩"从候选里选 + 组合步骤"。这就是为什么便宜模型够用——**最难的部分（感知 + 验证）根本不在模型手里**。

## 2. OpenAI 兼容协议，天然多模型支持

底层只依赖 OpenAI 兼容的 `/chat/completions`：

```python
resp = client.retrying_post(
    f"{self.base_url}/chat/completions", body,
    timeout=self.timeout, retries=3,
    headers={"Authorization": f"Bearer {self.api_key}"},
)
```

所以换模型 = 换 `--model` 和 `--base-url`：

```powershell
mio-cua run "打开计算器，计算 3*4" --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

OpenAI / DeepSeek / 任何兼容 API 都是同一套代码。跑验收套件也一样：

```bash
python scripts/run_smoke_vdesk.py --only calculator,crossapp,explorer,notepad,web \
  --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

## 3. 便宜模型触发的工程改进（意外收获）

非视觉模型（比如 flash 档）不认识截图，这在早期反而是 bug：给非视觉 provider 发 `image_url` 会被 400 拒绝。于是 planner 加了**优雅降级**——如果请求因 400 失败且带图片，就移除图片消息重试一次：

```python
except Exception as e:
    if image_msg is not None and getattr(getattr(e, "response", None), "status_code", None) == 400:
        messages.remove(image_msg)   # non-vision provider: drop screenshot and retry
        resp = self.provider.generate(messages, tools=tools)
```

这个兜底让"纯文本模型 + 结构化场景图"成为一等公民，而不仅是"没视觉时凑合用"。

## 4. 五场景全绿，靠的是把不确定性从模型身上挪走

说句公道话：deepseek-v4-flash 也能跑通，不代表模型不重要。它跑通的关键是**系统把每一步的不确定性压到了最低**：

- **键盘输入优先于像素点击**：`key(keys="1")` 是确定性输入，而"点坐标"是概率输入，便宜模型的坐标推断更不可靠。
- **操作符预期标注**：按 `+` 时显示区不该变，感知层提前标注 `expected: display unchanged`，避免模型误判重复按键。
- **一动作一感知**：每步重新读屏，动作永不基于过期场景——这比"让模型更聪明"更管用。
- **硬守卫拦截假成功**：输入了文件名没按回车，`success` 会被拦下。

## 5. 成本视角

| 模型 | 单次 21 步跨应用任务（估算） |
|---|---|
| 旗舰视觉模型 | 高，且每步传截图 |
| flash 档 + 场景图 | 低，纯文本推理 + 结构化输入 |

架构的取舍很明确：**把贵的事（感知、验证）做成确定性的代码，把便宜的事（选动作、排步骤）交给模型。** 模型贵不贵，就不再是能不能用的问题，只是用起来多省的问题。

---

想亲眼看看便宜模型跑通桌面 Agent？五个场景的验收命令都在 README 里：
https://github.com/mldlbs/mio-cua
