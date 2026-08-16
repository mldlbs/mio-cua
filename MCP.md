# mio-cua MCP 接入指南

把 mio-cua 作为 MCP server 接入 Claude / Cursor / ChatGPT 等客户端，让 AI 能控制你的 Windows 桌面（文件整理、窗口操作、键盘鼠标输入）。

## 安装

```bash
cd desktop-agent
pip install -e .          # 安装 mio-cua 和 mio-cua-mcp 命令
pip install -e ".[vision]"  # 可选：OCR 依赖（rapidocr）
pip install -e ".[gpu]"     # 可选：onnxruntime-directml，GPU 加速感知推理
```

## 接入 Claude Desktop / Claude Code

在客户端 MCP 配置里注册 server。Claude Code 在项目或全局 `.mcp.json`：

```json
{
  "mcpServers": {
    "mio-cua": {
      "command": "mio-cua-mcp",
      "args": []
    }
  }
}
```

## 接入 Cursor

`~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "mio-cua": {
      "command": "mio-cua-mcp",
      "args": []
    }
  }
}
```

## 接入 OpenAI / ChatGPT（桌面端 MCP 支持）

在支持 MCP 的客户端中同样注册上面的 server 配置。

## 可用工具

| 工具 | 说明 |
| --- | --- |
| `mio_list_dir` | 列出目录内容（文件优先） |
| `mio_read_file` | 读取文本文件前 N 字符（默认 2000，可截断） |
| `mio_write_file` | 写入文本文件（create/append/write；覆盖需 allow_overwrite） |
| `mio_search_files` | 递归搜索文件（名称/扩展名/内容，上限 50 条） |
| `mio_make_dir` | 创建目录（递归） |
| `mio_move_file` | 移动单个文件到目录 |
| `mio_move_files` | 批量移动多个文件到同一目录 |
| `mio_launch` | 启动程序 / 打开文件或 URL |
| `mio_focus_window` | 聚焦窗口 |
| `mio_get_active_window` | 获取当前前台窗口标题 |
| `mio_click` | 屏幕坐标点击 |
| `mio_type` | 向聚焦控件输入文本 |
| `mio_key` | 发送按键/组合键（enter、ctrl+s 等） |
| `mio_observe_scene` | 感知活动窗口：元素列表（文本/类型/坐标/src/conf） |
| `mio_analyze_page` | 纯视觉解析网页为交互元素（OmniParser，无需 DOM/扩展） |
| `mio_vdesk` | 管理虚拟桌面隔离（ensure/close/left/right/num） |
| `mio_screenshot` | 保存活动窗口截图 PNG |
| `mio_ocr_text` | OCR 读取活动窗口可见文本（坐标） |
| `mio_list_windows` | 列出所有可见窗口标题 |
| `mio_close_window` | 按标题优雅关闭窗口（WM_CLOSE） |
| `mio_get_cursor` | 获取鼠标坐标 |
| `mio_move_mouse` | 移动鼠标（不点击，hover 用） |
| `mio_scroll` | 活动窗口滚动（正下负上） |
| `mio_clipboard_get` | 读取剪贴板文本 |
| `mio_clipboard_set` | 设置剪贴板文本（配合 ctrl+v 粘贴） |
| `mio_notify` | 桌面通知 |
| `mio_list_processes` | 列出运行进程（PID/名称/内存，可过滤） |
| `mio_kill_process` | 结束进程（按名称/PID，可选强制） |
| `mio_get_screen_info` | 显示器布局与 DPI scale |
| `mio_drag` | 从 A 拖到 B（移动图标/选范围/滑条） |
| `mio_sleep` | 等待 N 秒（应用加载/异步窗口） |

## 安全提示

- 这些工具操作**真实桌面**（移动鼠标、键盘、文件），只在你信任的客户端中启用
- 文件移动拒绝覆盖已存在文件
- 发布到 MCP Registry 前建议补充确认/沙箱机制
