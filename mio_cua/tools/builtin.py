from mio_cua.tools.registry import ToolRegistry
from mio_cua.tools import click, type as type_tool, key, scroll, wait, screenshot, launch, focus_window, move_mouse, success, fail
from mio_cua.tools import fs

_SCHEMAS = {
    "click": {"type": "function", "function": {"name": "click", "description": "Click mouse at coordinates or element", "parameters": {"type": "object", "properties": {
        "element_id": {"type": "integer"}, "x": {"type": "number"}, "y": {"type": "number"},
        "button": {"type": "string", "enum": ["left", "right"]}, "double": {"type": "boolean"}}}}},
    "type": {"type": "function", "function": {"name": "type", "description": "Type text", "parameters": {"type": "object", "properties": {
        "text": {"type": "string"}, "element_id": {"type": "integer"}}, "required": ["text"]}}},
    "key": {"type": "function", "function": {"name": "key", "description": "Send key combination like ctrl+c", "parameters": {"type": "object", "properties": {
        "keys": {"type": "string"}}, "required": ["keys"]}}},
    "scroll": {"type": "function", "function": {"name": "scroll", "description": "Scroll", "parameters": {"type": "object", "properties": {
        "direction": {"type": "string", "enum": ["up", "down"]}, "amount": {"type": "integer"}}}}},
    "wait": {"type": "function", "function": {"name": "wait", "description": "Wait seconds", "parameters": {"type": "object", "properties": {
        "seconds": {"type": "number"}}, "required": ["seconds"]}}},
    "screenshot": {"type": "function", "function": {"name": "screenshot", "description": "Take screenshot", "parameters": {"type": "object", "properties": {
        "region": {"type": "string"}}}}},
    "launch": {"type": "function", "function": {"name": "launch", "description": "Launch a program, command, or file path. To open a file with an app, pass the command with the path, e.g. 'notepad C:\\Users\\x\\Desktop\\data.txt' or 'calc'. App windows opened via launch are kept in background so you can open many in parallel.", "parameters": {"type": "object", "properties": {
        "command": {"type": "string"}}, "required": ["command"]}}},
    "focus_window": {"type": "function", "function": {"name": "focus_window", "description": "Focus a window by title", "parameters": {"type": "object", "properties": {
        "title": {"type": "string"}}, "required": ["title"]}}},
    "move_mouse": {"type": "function", "function": {"name": "move_mouse", "description": "Move mouse (hover)", "parameters": {"type": "object", "properties": {
        "element_id": {"type": "integer"}, "x": {"type": "number"}, "y": {"type": "number"}}}}},
    "success": {"type": "function", "function": {"name": "success", "description": "Task complete", "parameters": {"type": "object", "properties": {
        "result": {"type": "string"}}, "required": ["result"]}}},
    "fail": {"type": "function", "function": {"name": "fail", "description": "Task failed", "parameters": {"type": "object", "properties": {
        "reason": {"type": "string"}}, "required": ["reason"]}}},
    "make_dir": {"type": "function", "function": {"name": "make_dir", "description": "Create a directory (recursively) if it does not exist. PREFERRED over clicking in Explorer for organizing files -- deterministic, no UI needed.", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}}, "required": ["path"]}}},
    "move_file": {"type": "function", "function": {"name": "move_file", "description": "Move ONE file into a directory. PREFERRED over Explorer click-and-drag when organizing files. Refuses to overwrite.", "parameters": {"type": "object", "properties": {
        "src": {"type": "string"}, "dest": {"type": "string"}}, "required": ["src", "dest"]}}},
    "move_files": {"type": "function", "function": {"name": "move_files", "description": "Move a LIST of files into one directory in a single call -- use this when organizing MANY files at once (e.g. all .pdf into 文档). More efficient than move_file per file. Refuses to overwrite.", "parameters": {"type": "object", "properties": {
        "files": {"type": "array", "items": {"type": "string"}}, "dest": {"type": "string"}}, "required": ["files", "dest"]}}},
    "list_dir": {"type": "function", "function": {"name": "list_dir", "description": "List files and directories under a path (files first, one per line). Use to inventory a folder instead of reading Explorer icons -- more complete and reliable.", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}}, "required": ["path"]}}},
    "read_file": {"type": "function", "function": {"name": "read_file", "description": "Read a text file's first N characters (default 2000). Use to retrieve file contents the agent needs (e.g. reading numbers from a data file before computing).", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["path"]}}},
    "write_file": {"type": "function", "function": {"name": "write_file", "description": "Write text to a file. mode=create makes a new file (refuses if it exists), append adds to the end, write overwrites (requires allow_overwrite=True). Creates parent dirs.", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"},
        "mode": {"type": "string", "enum": ["create", "append", "write"]},
        "allow_overwrite": {"type": "boolean"}}, "required": ["path", "content"]}}},
    "search_files": {"type": "function", "function": {"name": "search_files", "description": "Recursively search a directory for files by name substring, extension, and/or content pattern. Returns up to 50 paths.", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "name": {"type": "string"}, "ext": {"type": "string"},
        "pattern": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["path"]}}},
}


def register_builtin_tools(registry: ToolRegistry):
    for name, func in [
        ("click", click.click),
        ("type", type_tool.type),
        ("key", key.key),
        ("scroll", scroll.scroll),
        ("wait", wait.wait),
        ("screenshot", screenshot.screenshot),
        ("launch", launch.launch),
        ("focus_window", focus_window.focus_window),
        ("move_mouse", move_mouse.move_mouse),
        ("success", success.success),
        ("fail", fail.fail),
        ("make_dir", fs.make_dir),
        ("move_file", fs.move_file),
        ("move_files", fs.move_files),
        ("list_dir", fs.list_dir),
        ("read_file", fs.read_file),
        ("write_file", fs.write_file),
        ("search_files", fs.search_files),
    ]:
        registry.register(name, func, _SCHEMAS[name])
