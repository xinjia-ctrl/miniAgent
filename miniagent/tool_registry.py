"""工具注册表：schema、权限、并行属性、直接命令解析和展示格式。"""

from __future__ import annotations

from .memory import remember, forget as forget_memory
from .tools import (
    apply_patch,
    find_files,
    git_diff,
    git_status,
    list_files,
    read_file,
    read_many_files,
    replace_in_file,
    run_shell,
    search_text,
    web_fetch,
    write_file,
)

EDIT_TOOLS = {"write_file", "replace_in_file", "apply_patch"}
PARALLEL_SAFE_TOOLS = {
    "read_file",
    "read_many_files",
    "list_files",
    "find_files",
    "search_text",
    "git_status",
    "git_diff",
    "web_fetch",
}
TOOL_PERMISSIONS = {
    "read_file": "read-only",
    "read_many_files": "read-only",
    "list_files": "read-only",
    "find_files": "read-only",
    "search_text": "read-only",
    "git_status": "read-only",
    "git_diff": "read-only",
    "delegate": "read-only",
    "remember": "workspace-write",
    "forget_memory": "workspace-write",
    "write_file": "workspace-write",
    "replace_in_file": "workspace-write",
    "apply_patch": "workspace-write",
    "run_shell": "shell-write",
    "web_fetch": "network",
}


def _param_schema(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


def _tool(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": _param_schema(properties or {}, required),
        },
    }


TOOLS = [
    _tool(
        "read_file",
        "读取文件内容（按行号范围）",
        {
            "path": {"type": "string", "description": "文件路径"},
            "start": {"type": "integer", "description": "起始行号", "default": 1},
            "end": {"type": "integer", "description": "结束行号", "default": 1000},
        },
        ["path"],
    ),
    _tool(
        "list_files",
        "列出目录内容",
        {"path": {"type": "string", "description": "目录路径", "default": "."}},
    ),
    _tool(
        "find_files",
        "按文件名模式查找工作区文件，自动跳过 .git、缓存和依赖目录。",
        {
            "pattern": {
                "type": "string",
                "description": "文件名模式，例如 *.py 或 test_*.py",
                "default": "*",
            },
            "path": {"type": "string", "description": "搜索起点目录", "default": "."},
            "max_results": {"type": "integer", "description": "最多返回多少条", "default": 200},
        },
    ),
    _tool(
        "search_text",
        "在工作区内搜索文本内容，优先使用 rg，适合定位函数、类、配置和报错。",
        {
            "pattern": {"type": "string", "description": "要搜索的文本或正则"},
            "path": {"type": "string", "description": "搜索路径", "default": "."},
            "max_results": {"type": "integer", "description": "最多返回多少条", "default": 200},
            "context": {"type": "integer", "description": "上下文行数 0-5", "default": 0},
        },
        ["pattern"],
    ),
    _tool(
        "read_many_files",
        "一次读取多个文件的指定行号范围，适合批量查看相关文件。",
        {
            "paths": {
                "type": "array",
                "description": "文件路径列表",
                "items": {"type": "string"},
            },
            "start": {"type": "integer", "description": "起始行号", "default": 1},
            "end": {"type": "integer", "description": "结束行号", "default": 400},
            "max_files": {"type": "integer", "description": "最多读取文件数", "default": 10},
        },
        ["paths"],
    ),
    _tool(
        "run_shell",
        "执行单条简单命令；不支持管道、重定向、命令串联或嵌套 shell。优先使用专用文件和 Git 工具。",
        {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时秒数", "default": 20},
        },
        ["command"],
    ),
    _tool(
        "write_file",
        "写入文件。默认不覆盖已有文件，适合创建新文件；覆盖时必须显式设置 overwrite=true。",
        {
            "path": {"type": "string", "description": "工作区内文件路径"},
            "content": {"type": "string", "description": "完整文件内容"},
            "overwrite": {"type": "boolean", "description": "是否允许覆盖已有文件", "default": False},
            "create_dirs": {"type": "boolean", "description": "父目录不存在时是否创建", "default": False},
        },
        ["path", "content"],
    ),
    _tool(
        "replace_in_file",
        "在文件中做精确文本替换。默认要求 old_text 只出现一次，避免误替换。",
        {
            "path": {"type": "string", "description": "工作区内文件路径"},
            "old_text": {"type": "string", "description": "要替换的原文"},
            "new_text": {"type": "string", "description": "替换后的文本"},
            "expected_replacements": {"type": "integer", "description": "期望替换次数，默认 1", "default": 1},
        },
        ["path", "old_text", "new_text"],
    ),
    _tool(
        "apply_patch",
        "批量应用多个精确文本替换补丁；任一补丁校验失败时不会修改任何文件。",
        {
            "patches": {
                "type": "array",
                "description": "补丁列表",
                "items": _param_schema(
                    {
                        "path": {"type": "string", "description": "工作区内文件路径"},
                        "old_text": {"type": "string", "description": "要替换的原文"},
                        "new_text": {"type": "string", "description": "替换后的文本"},
                        "expected_replacements": {
                            "type": "integer",
                            "description": "期望替换次数，默认 1",
                            "default": 1,
                        },
                    },
                    ["path", "old_text", "new_text"],
                ),
            },
        },
        ["patches"],
    ),
    _tool("git_status", "查看当前 Git 工作区状态"),
    _tool(
        "git_diff",
        "查看未暂存 diff，可选传入 path 限制到单个文件或目录",
        {"path": {"type": "string", "description": "可选，工作区内路径"}},
    ),
    _tool(
        "web_fetch",
        "抓取 HTTP/HTTPS 网页并返回提取后的文本内容，需要 network 权限。",
        {
            "url": {"type": "string", "description": "要抓取的网页 URL"},
            "timeout": {"type": "integer", "description": "超时秒数", "default": 20},
            "max_chars": {"type": "integer", "description": "最多返回字符数", "default": 20000},
        },
        ["url"],
    ),
    _tool(
        "remember",
        "记住一条信息（持久化，跨会话保留）",
        {
            "tag": {"type": "string", "description": "分类标签，如 用户偏好、项目信息、问题记录"},
            "content": {"type": "string", "description": "要记住的内容"},
            "importance": {"type": "integer", "description": "重要性 1-5，越高越优先保留", "default": 1},
        },
        ["tag", "content"],
    ),
    _tool(
        "forget_memory",
        "删除一条已记住的信息",
        {"mem_id": {"type": "string", "description": "记忆 ID"}},
        ["mem_id"],
    ),
    _tool(
        "delegate",
        "把一个调查型子任务交给只读子 agent。子 agent 只能读文件、搜索、看 Git 状态和抓取网页。",
        {
            "task": {"type": "string", "description": "要调查的问题或子任务"},
            "max_steps": {"type": "integer", "description": "子 agent 最多工具循环步数", "default": 3},
        },
        ["task"],
    ),
]


def build_func_map(delegate_func):
    return {
        "read_file": read_file,
        "read_many_files": read_many_files,
        "list_files": list_files,
        "find_files": find_files,
        "search_text": search_text,
        "run_shell": run_shell,
        "write_file": write_file,
        "replace_in_file": replace_in_file,
        "apply_patch": apply_patch,
        "git_status": git_status,
        "git_diff": git_diff,
        "web_fetch": web_fetch,
        "remember": remember,
        "forget_memory": forget_memory,
        "delegate": delegate_func,
    }


def _int_arg(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_direct_command(text):
    text = text.strip()
    if not text:
        return None
    if text.startswith("!"):
        return ("run_shell", {"command": text[1:].strip()})
    parts = text.split(maxsplit=1)
    name = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if name == "read_file":
        tokens = rest.split()
        return ("read_file", {
            "path": tokens[0] if tokens else "",
            "start": _int_arg(tokens[1], 1) if len(tokens) > 1 else 1,
            "end": _int_arg(tokens[2], 1000) if len(tokens) > 2 else 1000,
        })
    if name == "read_many_files":
        tokens = rest.split()
        return ("read_many_files", {
            "paths": tokens[0].split(",") if tokens else [],
            "start": _int_arg(tokens[1], 1) if len(tokens) > 1 else 1,
            "end": _int_arg(tokens[2], 400) if len(tokens) > 2 else 400,
        })
    if name == "list_files":
        return ("list_files", {"path": rest or "."})
    if name == "find_files":
        tokens = rest.split(maxsplit=1)
        return ("find_files", {"pattern": tokens[0] if tokens else "*", "path": tokens[1] if len(tokens) > 1 else "."})
    if name == "search_text":
        tokens = rest.split(maxsplit=1)
        return ("search_text", {"pattern": tokens[0] if tokens else "", "path": tokens[1] if len(tokens) > 1 else "."})
    if name == "run_shell":
        return ("run_shell", {"command": rest})
    if name == "git_status":
        return ("git_status", {})
    if name == "git_diff":
        return ("git_diff", {"path": rest.strip() or None})
    if name == "web_fetch":
        return ("web_fetch", {"url": rest.strip()})
    if name == "delegate":
        return ("delegate", {"task": rest.strip(), "max_steps": 3})
    if name == "remember":
        tokens = rest.split(maxsplit=1)
        return ("remember", {"tag": tokens[0] if tokens else "", "content": tokens[1] if len(tokens) > 1 else "", "importance": 3})
    if name == "forget_memory":
        return ("forget_memory", {"mem_id": rest.strip()})
    return None


def format_tool_call(name, args):
    if not args:
        return f"{name}()"
    if name == "read_file":
        return f"read_file({args.get('path', '')}, {args.get('start', 1)}-{args.get('end', 1000)})"
    if name == "read_many_files":
        return f"read_many_files({len(args.get('paths') or [])} 个文件)"
    if name == "list_files":
        return f"list_files({args.get('path', '.')})"
    if name == "find_files":
        return f"find_files({args.get('pattern', '*')}, {args.get('path', '.')})"
    if name == "search_text":
        return f"search_text({args.get('pattern', '')}, {args.get('path', '.')})"
    if name == "run_shell":
        return f"run_shell({args.get('command', '')})"
    if name == "web_fetch":
        return f"web_fetch({args.get('url', '')})"
    if name == "delegate":
        return f"delegate({str(args.get('task', ''))[:80]})"
    if name in ("write_file", "replace_in_file", "git_diff"):
        return f"{name}({args.get('path', '')})"
    if name == "apply_patch":
        return f"apply_patch({len(args.get('patches') or [])} 个补丁)"
    return f"{name}(...)"


def tools_help():
    return """可直接调用的工具命令：

read_file 路径 [起始行] [结束行]
read_many_files 文件1,文件2 [起始行] [结束行]
list_files [目录]
find_files [模式] [目录]
search_text 关键词 [目录]
git_status
git_diff [路径]
web_fetch URL
delegate 调查任务
remember 标签 内容
forget_memory 记忆ID
!命令                  执行 shell 命令"""
