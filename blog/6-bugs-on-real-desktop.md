# 我把 AI 接到真实 Windows 桌面的踩坑记录（6 个工程 bug）

> Draft for 思否/掘金. Repo: https://github.com/mldlbs/mio-cua

---

让 AI 在**真实** Windows 桌面上干活，和跑 mock 完全不是一回事。调优五个验收场景（记事本/计算器/资源管理器/跨应用/网页）时修掉了 6 个工程 bug，每个都是"模拟器里永远遇不到、真实桌面必然踩"的坑。记录如下。

## Bug 1：基于过期场景执行动作（stale scene execution）

**现象**：一个 plan 里规划了多个动作，执行时用**同一份**观察结果连续操作。第一次点击改变了屏幕，后续动作还在对着旧场景决定坐标。

**根因**：把"观察 → 规划 → 执行"看成了可以批量化的流水线，忽略了桌面交互是**有状态**的——每个动作都会改变世界。

**修法**：循环强制**一动作一感知**——每执行一个动作后重新 observe 再重新规划：

```python
# Only ONE action per observation: the screen changes after every action,
# so subsequent actions in the same plan were decided against a stale scene.
if i + 1 < len(plan.actions):
    break
```

配合 OCR 内容签名缓存，屏幕没变的窗口直接复用感知结果，代价几乎为零。

## Bug 2：UWP 计算器聚焦失败

**现象**：`calc` 启动的是新版 UWP 计算器，`focus_window` 按标题聚焦有时抓不住窗口，按键落到前台窗口而不是计算器。

**根因**：UWP 应用窗口结构与 Win32 不同，标题匹配 + SetForegroundWindow 的组合对它的窗口类不可靠。

**修法**：Recovery 层统一处理——动作失败后先 `focus_window` 再重试，每次动作最多重试 2 次：

```python
RECOVERABLE = ("click", "type", "key", "scroll", "move_mouse")
# retry: focus the active window, then re-issue the action
```

## Bug 3：`+` 键被当分隔符 split 失败

**现象**：跨应用场景要求 `key(keys="+")` 发送加号键，结果一直报错，表达式停在 `12` 发不出去。

**根因**：工具参数解析把 `+` 当成了分隔符去 split，`key(keys="+")` 的 `+` 被截断。一个字符的解析 bug，卡住整个求和场景。

**修法**：修正参数分隔逻辑，`+` 作为合法的 key 值原样传递。教训：**输入内容永远不该参与控制面解析。**

## Bug 4：浏览器 PATH 找不到

**现象**：`mio_launch("msedge https://...")` 在部分会话里报找不到浏览器，网页场景起不来。

**根因**：某些环境（vdesk 隔离、service 会话、PATH 精简过的 shell）里 `msedge` 不在 PATH，直接交给 CreateProcess 找不到可执行文件。

**修法**：launch 工具对常见浏览器做**路径解析回退**——按已知安装位置（Program Files / 用户 AppData）补齐 `msedge.exe` 等路径，而不是只靠 PATH。

## Bug 5：重命名未按回车，success 假成功

**现象**：资源管理器场景里，agent 输入了文件夹名 `smoke_demo_folder` 但**没按回车**就调 `success`。check 阶段 `dir_exists` 失败——文件夹根本没建成。

**根因**：重命名框的编辑在按下 Enter 之前**不生效**，但 LLM 认为"我输入了名字 = 做完了"。

**修法**：loop 层加**硬守卫**——凡是 `type` 没有 `element_id`（聚焦的重命名框/文件名框）且近期没有确认动作（Enter/Save/ctrl+s），`success` 被拦截：

```python
_BLOCKED: you typed a name but never pressed enter to apply it
-- the edit is NOT saved. Call key(keys="enter") to confirm.
```

顺带补了三个提示型守卫：创建新文件夹后没输入名字（`_rename_hint`）、输入后没确认（`_confirm_hint`）、已完成收尾却反复验证不结束（`_completion_hint`）。

## Bug 6：元素 id 逐帧漂移，点击错控件

**现象**：计算器按钮在两次观察之间 id 变了，按 `element_id` 点击点到了别的数字。

**根因**：id 按 UIA/OCR 的枚举顺序分配，而枚举顺序跨帧不稳定——同一个物理按钮每次扫描顺序都可能不同。

**修法**：合并后**按屏幕位置排序再分配 id**（`(top, left)`，无位置框排最后），让同一个控件稳定地拿到同一个 id：

```python
merged.sort(key=_stable_sort_key)
for i, e in enumerate(merged):
    e.id = i
```

计算器场景的验收指令也改为**键盘输入优先**："元素 id 可能逐帧漂移，键盘输入更可靠"。

---

## 共性的教训

1. **真实桌面的非确定性是常态**——mock 里一切稳定，真实环境每次观察都可能不同。设计必须以"重新感知"为前提。
2. **确定性输入优于概率输入**——键盘 > 坐标点击；能走工具的走工具（文件操作用 `move_files` 而不是在资源管理器里拖拽）。
3. **验证比决策重要**——Scaffold 假成功和"输入了但没应用"都是决策正确但验证缺失。验收 check（文件存在 + 内容包含）是最后防线。
4. **每一步的失败都要可恢复**——Recovery（聚焦窗口后重试）+ 循环守卫（重复动作 ≥6 次判 FAIL）避免空转。

这些 bug 没有一个是"AI 不够聪明"，全是**工程结构**问题——这也正是把它修成开箱即用工具的关键。

五个场景的验收命令和全部修复链在仓库：
https://github.com/mldlbs/mio-cua
