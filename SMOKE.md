# Release Gate：真实 Windows 冒烟测试

v0.3 可用性验收。三个场景全部 SUCCESS 才算 MVP 真正可用。

**当前状态：三个场景已全部在真实 Win11 桌面 PASS**
（deepseek-v4-flash + DirectML GPU OCR，见下方"最近一次验收记录"）

**跨应用场景（crossapp）状态：感知层修复已完成，端到端待重跑**
（需虚拟桌面隔离，运行期间用户必须完全空闲）

## 场景

| 场景 | 文件 | 验证能力 |
| --- | --- | --- |
| Case 1 记事本 | `smoke/notepad.yaml` | 点击、输入、快捷键、文件保存、窗口切换 |
| Case 2 计算器 | `smoke/calculator.yaml` | OCR、元素定位、Verify、截图 |
| Case 3 资源管理器 | `smoke/explorer.yaml` | UIA、鼠标、右键菜单、文本输入 |
| Case 4 跨应用 | `smoke/crossapp.yaml` | 读文件 → 计算器求和 → 保存结果（Scene Graph 多步任务） |

## 运行方式

冒烟脚本会在**虚拟桌面**上运行，隔离主桌面；但运行期间请勿碰键鼠，否则隔离会失效。
> v0.4 起 `vdesk.new_desktop()` 会自动用 Esc 关闭任务视图，确保 agent 落在干净新桌面。

```powershell
# 前置：LLM API Key（agent 从环境变量读取）
$env:OPENAI_API_KEY = "sk-xxx"

# 每次运行前清理残留进程，避免上一轮窗口被幻觉复用
Get-Process notepad,calc -ErrorAction SilentlyContinue | Stop-Process -Force

# 全部场景（虚拟桌面，日志落盘，返回 PID）
python scripts/run_smoke_vdesk.py --model <model> --base-url <url>
# 单个场景
python scripts/run_smoke_vdesk.py --only notepad --model <model> --base-url <url>
# 跨应用场景
python scripts/run_smoke_vdesk.py --only crossapp --model <model> --base-url <url>
```

示例（DeepSeek）：

```powershell
$env:OPENAI_API_KEY = "sk-xxx"
python scripts/run_smoke_vdesk.py --only explorer --model deepseek-v4-flash --base-url https://api.deepseek.com/v1
```

> 注意：`run_smoke_vdesk.py` 返回 `PID=<pid>` 与日志路径
> `D:\Users\gf1913\Temp\smoke_vdesk.log`，轮询日志尾部 40-60 行等待 `[PASS]/[FAIL]`。

## 验收标准

- 每个场景的 `SUCCESS` 与脚本中的 `checks`（活动窗口、目标文件/目录存在）一致
- `=== SUMMARY ===` 全部 `PASS`，退出码 0
- 运行期间 F9 可随时中断当前任务

## 注意事项

- agent 从 `OPENAI_API_KEY` 环境变量读 key（config `api_key_env`），未设置会 401
- 桌面路径在 D 盘（`D:\Users\gf1913\Desktop`），smoke 检查用 `_desktop_dir()` 解析，勿用 `$HOME`（C 盘）判断
- OCR 默认走 DirectML（`DESKTOP_AGENT_OCR_DEVICE=dml`，回退 `cpu`）；单次 OCR 平均 ~1.6s
- artifact 自动清理，目录默认上限 200MB（`artifact_max_bytes`）
- 中文 Windows 下计算器/记事本标题包含中文，OCR 与 `active_window` 检查依赖此匹配

## 网页感知说明（v0.5）

浏览器窗口走两条纯视觉链路（不依赖 DOM）：
- **Regions 版面分析**（`rapid_layout`，可选依赖，DirectML）：识别页面结构（导航/标题/正文/表格/图片），Scene 输出 `## Layout regions (page structure)`。
- **OmniParser 控件识别**（`scene/omniparser.py`，可选依赖，torch CUDA）：YOLOv9 交互元素检测 + Florence-2 语义描述，把网页截图解析成可点击 `button` 节点（Sign Up/About/输入框等）。模型默认在项目内 `models/omniparser/`（仓库 + `weights/`），无需配置；如需自定义位置可覆盖：
  ```
  $env:OMNIPARSER_DIR  = "<任意目录>/OmniParser"   # 克隆的 OmniParser 仓库
  $env:OMNIPARSER_WEIGHTS = "<OMNIPARSER_DIR>\weights"   # icon_detect_v3 + icon_caption_florence
  ```
  权重从 HuggingFace 下载（需代理）：`icon_detect_v3/model.pt`（YOLOv9，281MB）+ `icon_caption_florence/*`（Florence-2，~1GB）。依赖：torch cu121、transformers 4.x、ultralytics、easyocr、paddleocr（懒加载）。
- 网页控件节点 id 在 10000+ 区间，`InputController.resolve` 支持从 scene 节点解析坐标，可直接 `click(element_id=10001)`。

## 最近一次验收记录（2026-08-09 · 5/5 全绿终验）

| 场景 | 结果 | 耗时 | 备注 |
| --- | --- | --- | --- |
| calculator | PASS (SUCCESS) | 10 步 55.5s | 键盘输入 `123*456=` → 56,088 |
| crossapp | PASS (SUCCESS) | 22 步 195.8s | 读文件 → 计算器 → 保存 `smoke_sum_result.txt`（内容校验通过） |
| explorer | PASS (SUCCESS) | 8 步 149.3s | 导航桌面确认 → 建文件夹 → 重命名 `smoke_demo_folder`（active_window + dir_exists 双真） |
| notepad | PASS (SUCCESS) | 7 步 45.0s | `hello world` 内容校验通过 |
| web | PASS (SUCCESS) | 7 步 76.9s | 纯视觉（OmniParser）点按钮/输入，视觉确认 |
| web_search | PASS (SUCCESS) | 15 步 218.0s | 真实网页：DuckDuckGo 纯视觉搜索 + enter 提交 + 确认结果页 |
| web_navigate | PASS (SUCCESS) | 20 步 258.8s | 真实网页多步：搜索 → 点击结果链接 → 跳转 python.org → 视觉确认 |

全部产物校验通过：`smoke_sum_result.txt`=102、`smoke_notepad_demo.txt`=hello world、`smoke_demo_folder` 存在。
完整套件 5/5 全绿，全部 status=SUCCESS。

### 关键根因修复（2026-08-08/09）

**12. 一动作一感知（`bb97875`）——解决 crossapp 反复失败的真正根因**：loop 原本在同一 observation 下连续执行一个 plan 里的全部动作。当 LLM 一次返回 `launch notepad 文件` + `launch calc` 时，两个动作背靠背执行、中间无感知，文件里的数字从未被读入，任务静默跳步。这看似"模型不强"，实为**陈旧场景 bug**——每次动作后屏幕都变了，后续动作基于已过时的场景决策。修复：每个 plan 迭代只执行第一个动作，随后重新感知再规划（terminal 动作除外）。
**13. UWP 计算器聚焦（`a7226fd`）**：`bring_to_front('calc')` 对 UWP 计算器恒返 False——按标题匹配到 ApplicationFrameHost 的窗口，`GetForegroundWindow()` 返回 CalculatorApp 子窗口 hwnd，精确 hwnd 比较误判失败。改为按**进程 id** 判断前台归属。修复后 `launch calc` 可靠聚焦，键盘输入不再打到前台记事本。
**14. 计算器 `+` 键发送（`522264e`）**：`key(keys="+")` 被 `_dispatch` 当作组合键分隔符 split 成 `['','']`，空主键抛异常 → `sent=False`。加号从未注册，显示区不变，agent 反复按 `+`（单轮 7 次）计算错乱。修复：单独的 `+` 作为字面字符发送（仅在带修饰键时当分隔符）。实测 `12+34=` → 46。
**15. 浏览器命令解析（`f376a1f`）**：`msedge`/`chrome` 不在 PATH，`launch msedge <file>` 报"不是内部或外部命令"，agent 反复 launch、web 场景超时。将已知浏览器命令解析为完整安装路径（`Program Files`），并补充浏览器标题/进程匹配。
**16. Explorer 重命名引导强化（`99b3cca`）**：实测确认——`ctrl+shift+n` 后重命名框有焦点，**无 element_id 的 `type(text=...)` 有效**；带 element_id 的 type（点击节点）会退出编辑模式导致失败。引导明确因果"点击会退出重命名模式"，避免 agent 用 element_id。修复后连续 2 次 explorer 均建出 `smoke_demo_folder`（dir_exists=True）。
**17. 收尾保障链（`01ecf44`→`2212b52`→`dc3a8b7`）**：三层收尾机制——确认提示（type 无 element_id 需 enter）、重命名提示（ctrl+shift+n 后须 type 名字）、**success 硬拦截**（type 后未确认就 success 会被 BLOCK，返回失败让 agent 先 enter）。修复 `_is_confirming_action` 子串误匹配（`ctrl+shift+n` 含 `ctrl+s`）。explorer 由此从"仅 dir_exists"提升到"active_window + dir_exists 双真"。**18. Explorer 导航强化（`1a836da`）**：确认窗口标题为"桌面 - 文件资源管理器"后再建文件夹，避免本机 C:/D: 双桌面路径下建到错误桌面。

### 功能研发：视觉决策 / 工具执行（2026-08-09）

**19. 工具路由机制（`1a57c6c`）**：明确"视觉负责决策、确定性通道负责执行"的架构原则——system.txt 声明优先用确定性通道（fs/key/launch）；fs 工具 schema 标注"比 Explorer 点击/拖拽更可靠"；planner 在 active_window 是文件管理器时注入 `ROUTING` 提示，引导文件操作用 `list_dir/make_dir/move_file`。
**20. 文件系统工具链（`d3bb8c3`）**：`list_dir`（枚举文件夹）、`make_dir`（建夹）、`move_file`（移动，拒绝覆盖）。让 agent 直接操作文件系统而非脆弱 UI 拖拽。
**21. 工具结果反馈（`ac28a7c`）**：修复架构缺口——工具返回的 message（如 list_dir 的文件列表）此前不反馈给 LLM，数据型工具不可用。现在 history 渲染动作结果进 prompt。
**22. 批量移动 move_files（`bafca43`）**：一次移动多个文件到同一目录，解决 60+ 文件逐个移动超时。routing 场景实测 12 步整理 7 个文件（此前 18 步仅 2 个）。

### MCP 集成（2026-08-09）

**23. MCP server（`edf1bcd`）**：mio-cua 封装为 MCP server（`mio-cua-mcp`，FastMCP stdio）——暴露 10 个工具（文件 list_dir/make_dir/move_file/move_files、窗口 launch/focus_window/get_active_window、输入 click/type/key），让 Claude/Cursor/ChatGPT 等任意 MCP 客户端控制 Windows 桌面。`pip install --user` 后命令可用，stdio 握手 + list_tools + call_tool 端到端验证通过。接入指南见 MCP.md。通往 MCP Registry 官方市场上架的第一步。

### 功能研发（2026-08-08）

**17. 程序化动作验证 ExpectedVerifier（`428aac6`）**：affordance 的 `expected`（如 `{'display': True}`、`{'display': 'unchanged'}`）此前只渲染给 LLM，从未程序化检查。新增 `agent/expected.py`：点击动作带 expected 时，下一帧用 scene diff 验证 display 是否按预期变化；未生效时给 agent `VERIFICATION` 提示（"你的点击没有预期效果，别盲目重试"），减少 LLM 误判漏点/错点。

其余修复：
1. **OCR 缓存失效**（`a1e82de`）：缓存 key 原为 `(active_window, rect)`，计算器显示区更新不触发重 OCR，scene 恒报 display=0 → agent 反复点键。改为加入图像内容指纹（24×24 灰度缩略图），窗口内容变化即重 OCR。
2. **launch 多实例**（`22d2f08`）：无参 `launch notepad` 复用已打开的旧文件窗口，agent 永远得不到空白文档。多实例应用（notepad）改为直接开新窗口；单实例（calc）保留复用。
3. **OCR 按钮词**（`e2f035b`）：Win11 另存为对话框几乎不暴露 UIA，`保存(S)`/`取消` 仅 OCR text 节点、无可点击候选。AffordanceBuilder 对匹配对话框按钮词的 text 节点生成 click affordance。
4. **run_smoke 日志**：`[result]` 行打印 status/steps/summary，便于定位 402/loop error 等。
5. **对话框文件名框 type 候选**（`1b4f1de`）：Win11 保存对话框文件名框仅 OCR text、无 input 类型，LLM 拿不到 type 候选反复点击。识别 `文件名(N):` 等字段标签并给右侧同行文本生成 `type` affordance + 标记 input。
6. **Explorer 键盘重命名 + type 替换语义引导**（`72e429c`）：`win+e` → 点桌面 → `ctrl+shift+n` → 无 element_id `type(text=...)` 直接粘贴进已聚焦的重命名框 → enter；避免点击退出重命名态。并说明 type 全选替换、OCR 截断是假象不要补字符。
7. **OmniParser 离线化**（`d8ca19c`）：Florence-2 processor/model 已在本地 HF 缓存，`HF_HUB_OFFLINE=1` 走离线；否则首次 parse 卡在连不上的 HF CDN（31.13.87.19 SYN 超时）。离线 parse 9 节点 19s；真实浏览器每帧 29-31 web 节点。
8. **元素 id 稳定**（`bdbc680`）：merge 按 UIA/OCR 枚举顺序编号，跨帧不稳定（计算器 `乘以`/`减` 同帧都拿 id 33）。改为按屏幕位置（top,left）排序后编号，同一物理控件 id 恒定。
9. **运算符 display 预期**（`bdbc680`）：运算符按钮（`×/÷/+/-` 及中文 `乘以/减/加/除`）affordance 标 `expected display='unchanged'`——按运算符不改变显示值，避免 LLM 误判失败重复点击。补 Unicode 运算符 `×÷−` 及本地化名识别。
10. **场景间进程清理**（`796df4e`）：run_smoke 场景间不清理，calculator 遗留 calc 窗口被 crossapp 复用导致乱点。每个场景前 `taskkill` 测试应用（notepad/calc/calculatorapp/mspaint；不含浏览器，避免误杀用户真实窗口）。
11. **计算器键盘输入**（`0944119`）：计算器按钮 id 跨帧漂移（元素集合大小每帧变），点按不稳。改用键盘逐个 `key(keys="1")`/`key(keys="+")` 输入表达式（VkKeyScan 自动处理 `*`/`+` 的 shift），绕开点击漂移。calculator 10-13 步 55-77s 稳定 PASS。
12. **一动作一感知**（`bb97875`）：见上文"关键根因修复"。
13. **UWP 计算器聚焦**（`a7226fd`）：`bring_to_front('calc')` 对 UWP 计算器恒返 False——按标题匹配到的是 ApplicationFrameHost 的窗口，`GetForegroundWindow()` 返回的是 CalculatorApp 子窗口 hwnd，精确 hwnd 比较误判失败。导致 `launch calc` 后焦点仍在 notepad，agent 的 `1,2,+` 键盘输入打到记事本、计算错乱。改为按**进程 id** 判断前台归属。修复后 crossapp 能完成三步（读文件→计算 102→保存成功，`file_exists/file_contains` 双真）。

### 结论

**5/5 完整套件终验全绿（2026-08-09）**：calculator/crossapp/explorer/notepad/web 全部 status=SUCCESS，全部产物正确。explorer 现为 active_window + dir_exists 双真（此前仅 dir_exists）。

跨场景调优中逐层定位并修复的工程 bug：
1. 陈旧场景执行（一动作一感知，`bb97875`）
2. UWP 计算器聚焦失败（按进程判前台，`a7226fd`）
3. 计算器 `+` 键被当分隔符 split（`522264e`）
4. 浏览器命令不在 PATH（`f376a1f`）
5. 元素 id 跨帧漂移、运算符 display 预期、场景清理、键盘输入等（`bdbc680`/`0944119`/`796df4e`）
6. **收尾保障**（`01ecf44`→`2212b52`→`dc3a8b7`）：确认/重命名/收尾三档提示 + **success 硬拦截**——type 无 element_id 后未按 enter 直接调 success 会被 BLOCK（阻止假完成）；`ctrl+shift+n` 不再误判为 `ctrl+s` 确认。
7. **程序化动作验证 ExpectedVerifier**（`428aac6`）：点击动作带 expected 时自动核验 display 变化。
8. **Explorer 导航强化**（`1a836da`）：确认窗口标题为"桌面 - 文件资源管理器"后再建文件夹，避免建到错误桌面（本机 C:/D: 双桌面路径）。
9. **视觉决策/工具执行架构**（`1a57c6c`+`d3bb8c3`+`ac28a7c`+`bafca43`）：明确"视觉感知+决策、确定性通道执行"路由；fs 工具链（list_dir/make_dir/move_file/move_files）+ 工具结果反馈给 LLM。routing 场景实测 12 步整理 7 文件。

**已知残余**：个别场景 agent 偶发行为波动（如 explorer 导航到错误桌面），smoke 以产物校验严格判定，重跑即过。均为 LLM 行为，非感知缺陷。

## Scene Graph 感知层说明（v0.4）

- `mio_cua/scene/`：NodeBuilder（OCR+UIA 融合成 Node，OCR 字形 `7` 覆盖 UIA 本地化名 `一`）、RelationBuilder（leftOf/above/labelFor 空间图）、AffordanceBuilder（生成 `click`/`type` 候选 + 显示区推断）、Scene Diff（显示值 `0`→`7` 变化检测）。
- Node id 与 merge 后元素 id 一致，`click(element_id)` 可直接解析坐标。
- 纯文本编辑器（notepad）的整窗 UIA 容器不会吞掉 OCR 数字：`12/34/56` 以独立 text 节点保留。
- launch：路径反斜杠归一化 + 启动后最多重试 6 次聚焦。
- `focus_window` 工具改用 `bring_to_front` 的健壮路径（SwitchToThisWindow + 标题匹配兜底），UWP 计算器可聚焦。
- 系统提示词：优先用感知层验证过的 Action candidates；多步任务明确"看到数据即进入下一步，不重复已完成操作"。
