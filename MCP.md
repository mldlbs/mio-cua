# mio-cua MCP 接入指南

把 mio-cua 作为 MCP server 接入 Claude / Cursor / ChatGPT 等客户端，让 AI 能控制你的 Windows 桌面（文件整理、窗口操作、键盘鼠标输入）。

## 安装

```bash
cd desktop-agent
pip install -e .          # 安装 mio-cua 和 mio-cua-mcp 命令
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
| `mio_make_dir` | 创建目录（递归） |
| `mio_move_file` | 移动单个文件到目录 |
| `mio_move_files` | 批量移动多个文件到同一目录 |
| `mio_launch` | 启动程序 / 打开文件或 URL |
| `mio_focus_window` | 聚焦窗口 |
| `mio_get_active_window` | 获取当前前台窗口标题 |
| `mio_click` | 屏幕坐标点击 |
| `mio_type` | 向聚焦控件输入文本 |
| `mio_key` | 发送按键/组合键（enter、ctrl+s 等） |

## 安全提示

- 这些工具操作**真实桌面**（移动鼠标、键盘、文件），只在你信任的客户端中启用
- 文件移动拒绝覆盖已存在文件
- 发布到 MCP Registry 前建议补充确认/沙箱机制
