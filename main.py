"""常驻交互终端：ReAct 工具调用 + 会话管理 + 持久化存档"""

import argparse
import sys
import json
from models import create_backend
from config import BACKEND
from tools import (
    read_file, list_files, run_shell,
    write_file, replace_in_file, apply_patch,
    git_status, git_diff,
)
from session import (
    create_session, save_message, load_messages,
    list_sessions, get_session, rename_session, delete_session,
)
from context import trim_messages
from memory import remember, forget as forget_memory, build_memory_block
from workspace import get_context

backend = None
VERBOSE_TOOLS = False

# Windows 终端编码兼容（强制 UTF-8 输出）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys, "stdout"):
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容（按行号范围）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "start": {"type": "integer", "description": "起始行号", "default": 1},
                    "end": {"type": "integer", "description": "结束行号", "default": 200},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出目录内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径", "default": "."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "执行 shell 命令。危险命令会要求用户确认，优先使用专用文件和 Git 工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "integer", "description": "超时秒数", "default": 20},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件。默认不覆盖已有文件，适合创建新文件；覆盖时必须显式设置 overwrite=true。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内文件路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                    "overwrite": {"type": "boolean", "description": "是否允许覆盖已有文件", "default": False},
                    "create_dirs": {"type": "boolean", "description": "父目录不存在时是否创建", "default": False},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "在文件中做精确文本替换。默认要求 old_text 只出现一次，避免误替换。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内文件路径"},
                    "old_text": {"type": "string", "description": "要替换的原文"},
                    "new_text": {"type": "string", "description": "替换后的文本"},
                    "expected_replacements": {"type": "integer", "description": "期望替换次数，默认 1", "default": 1},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "批量应用多个精确文本替换补丁；任一补丁校验失败时不会修改任何文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "patches": {
                        "type": "array",
                        "description": "补丁列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "工作区内文件路径"},
                                "old_text": {"type": "string", "description": "要替换的原文"},
                                "new_text": {"type": "string", "description": "替换后的文本"},
                                "expected_replacements": {"type": "integer", "description": "期望替换次数，默认 1", "default": 1},
                            },
                            "required": ["path", "old_text", "new_text"],
                        },
                    },
                },
                "required": ["patches"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "查看当前 Git 工作区状态",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "查看未暂存 diff，可选传入 path 限制到单个文件或目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "可选，工作区内路径"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "记住一条信息（持久化，跨会话保留）",
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "分类标签，如 用户偏好、项目信息、问题记录"},
                    "content": {"type": "string", "description": "要记住的内容"},
                    "importance": {"type": "integer", "description": "重要性 1-5，越高越优先保留", "default": 1},
                },
                "required": ["tag", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": "删除一条已记住的信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "mem_id": {"type": "string", "description": "记忆 ID"},
                },
                "required": ["mem_id"],
            },
        },
    },
]

FUNC_MAP = {
    "read_file": read_file,
    "list_files": list_files,
    "run_shell": run_shell,
    "write_file": write_file,
    "replace_in_file": replace_in_file,
    "apply_patch": apply_patch,
    "git_status": git_status,
    "git_diff": git_diff,
    "remember": remember,
    "forget_memory": forget_memory,
}

SYSTEM_PROMPT = """你是一个可以操作电脑的 AI 智能体。你有以下能力：
- read_file: 读取文件
- list_files: 列出目录
- run_shell: 执行 shell 命令
- write_file: 创建或覆盖文件
- replace_in_file: 精确替换文件片段
- apply_patch: 批量应用精确替换补丁
- git_status: 查看 Git 状态
- git_diff: 查看未暂存 diff
- remember: 记住信息（跨会话保留，对话结束也不会丢）
- forget_memory: 删除已记住的信息

请按 ReAct 模式工作：
1. 思考当前任务需要做什么（Thought）
2. 调用合适的工具（Action）
3. 观察工具返回的结果（Observation）
4. 重复直到任务完成，然后给出最终答案

注意：你可以连续多次调用工具，不需要一次只调一个。
重要：
- 当前系统是 Windows（不是 Linux/Mac），run_shell 中请使用 Windows 命令（dir、type、findstr 等），不要用 find、grep、xargs、wc 等 Linux 命令。
- 修改文件时优先使用 replace_in_file 或 apply_patch，创建文件时使用 write_file。
- 修改后请用 git_diff 检查变更。
- 当用户询问“你是谁、你有什么功能、如何使用、有哪些命令”等关于助手自身能力的问题时，优先直接回答，不要为了回答这类问题读取文件或列目录。"""


def _parse_repl(text):
    """解析 REPL 指令，返回 (工具名, 参数字典) 或 None"""
    text = text.strip()
    if not text:
        return None

    # !command → run_shell
    if text.startswith("!"):
        return ("run_shell", {"command": text[1:].strip()})

    # 精确匹配前几个工具名
    parts = text.split(maxsplit=1)
    name = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if name == "read_file":
        tokens = rest.split()
        path = tokens[0] if tokens else ""
        start = int(tokens[1]) if len(tokens) > 1 else 1
        end = int(tokens[2]) if len(tokens) > 2 else 200
        return ("read_file", {"path": path, "start": start, "end": end})

    if name == "list_files":
        return ("list_files", {"path": rest or "."})

    if name == "run_shell":
        return ("run_shell", {"command": rest})

    if name == "git_status":
        return ("git_status", {})

    if name == "git_diff":
        return ("git_diff", {"path": rest.strip() or None})

    if name == "remember":
        # remember tag content
        tokens = rest.split(maxsplit=1)
        tag = tokens[0] if tokens else ""
        content = tokens[1] if len(tokens) > 1 else ""
        return ("remember", {"tag": tag, "content": content, "importance": 3})

    if name == "forget_memory":
        return ("forget_memory", {"mem_id": rest.strip()})

    return None


def _exec_direct(name, args):
    """直接执行工具并打印结果"""
    func = FUNC_MAP.get(name)
    if not func:
        print(f"未知工具: {name}")
        return ""
    try:
        result = func(**args)
        print(str(result))
        return str(result)
    except Exception as e:
        print(f"错误: {e}")
        return str(e)


def _is_capability_question(text):
    """识别关于助手自身能力和用法的常见问题"""
    normalized = text.strip().lower()
    if not normalized:
        return False
    if normalized in ("help", "帮助", "?"):
        return True

    keywords = (
        "你有什么功能",
        "你能做什么",
        "有什么功能",
        "有哪些功能",
        "怎么使用",
        "如何使用",
        "使用方法",
        "有哪些命令",
        "你是谁",
    )
    return any(keyword in normalized for keyword in keywords)


def _capability_answer():
    """本地回答助手能力，避免为元问题触发工具调用"""
    return """我是一个简易 CLI 代码 Agent，可以在当前工作区里帮你做这些事：

- 读取文件、列目录，理解项目结构和已有代码。
- 创建文件、精确替换代码片段、批量应用补丁。
- 执行命令；遇到删除、Git 重置等危险命令会要求确认。
- 查看 Git 状态和未暂存 diff。
- 保存会话历史和少量长期记忆，支持续接上下文。

常用直接命令：
- `read_file 路径 [起始行] [结束行]`
- `list_files [目录]`
- `git_status`
- `git_diff [路径]`
- `!命令` 执行 shell 命令

也可以直接用自然语言说需求，比如“帮我看一下这个项目结构”“给 main.py 加一个参数”“运行测试并修复报错”。"""


def _clean(obj):
    """递归清理 surrogate 字符"""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(obj, list):
        return [_clean(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _clean(value) for key, value in obj.items()}
    return obj


def _show_sessions():
    """打印历史会话列表"""
    sessions = list_sessions()
    if not sessions:
        print("  (暂无历史会话)")
        return
    for i, s in enumerate(sessions, 1):
        print(f"  {i}. {s['title']}  [{s['message_count']}条]  {s['updated_at']}")


def _print_header(session_id=None):
    """打印启动头部（bongo 风格）"""
    ws = get_context()
    W = 82

    def pad(text="", w=W):
        return "|" + text.ljust(w) + "|"

    def row(left, right=""):
        if right:
            gap = max(1, 44 - len(left))
            return "|" + left + " " * gap + right + " " * max(0, W - len(left) - gap - len(right)) + "|"
        return "|" + left.ljust(W) + "|"

    logo = [
        "           _       _    _                    _   ",
        " _ __ ___ (_)_ __ (_)  / \\   __ _  ___ _ __ | |_ ",
        "| '_ ` _ \\| | '_ \\| | / _ \\ / _` |/ _ \\ '_ \\| __|",
        "| | | | | | | | | | |/ ___ \\ (_| |  __/ | | | |_ ",
        "|_| |_| |_|_|_| |_|_/_/   \\_\\__, |\\___|_| |_|\\__|",
        "                            |___/                 ",
    ]

    print("+" + "=" * W + "+")
    print(pad(""))
    for ln in logo:
        print(pad(ln))
    print(pad(""))
    print(pad("                              miniAgent"))
    print(pad("                         local coding agent"))
    print(pad("                     calm terminal, ready for work"))
    print(pad(""))
    print("+" + "-" * W + "+")
    print(pad(""))

    branch = ws.branch or "-"
    model = backend.model
    status_text = "dirty" if ws.status != "clean" else "clean"

    label = "new session"
    if session_id:
        s = get_session(session_id)
        label = s.get("title", "unnamed")[:24]

    cwd_str = str(ws.cwd)
    if len(cwd_str) > 60:
        cwd_str = "..." + cwd_str[-57:]

    print(row(f"  WORKSPACE   {cwd_str}"))
    print(row(f"  MODEL       {model}", f" BRANCH      {branch}"))
    print(row(f"  STATUS      {status_text}", f" SESSION     {label}"))

    if ws.recent_commits:
        commit = _clean(ws.recent_commits[0][:58])
        print(row(f"  LATEST      {commit}"))

    print(pad(""))
    print("+" + "=" * W + "+")


def _build_system_content():
    """构建最新 system prompt：包含工作区快照和记忆"""
    ws = get_context()
    ws.refresh()
    ws_text = ws.text()
    mem_block = build_memory_block()
    extra = "\n\n".join(filter(None, [ws_text, mem_block]))
    return SYSTEM_PROMPT + ("\n\n" + extra if extra else "")


def _refresh_system_message(messages):
    """每轮请求前刷新 system 消息，避免 Git 状态和项目文档过期"""
    content = _build_system_content()
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = content
    else:
        messages.insert(0, {"role": "system", "content": content})


def _history_to_message(item):
    """会话存档消息转换为 API 消息，兼容旧版纯文本格式"""
    msg = {
        "role": item.get("role", "assistant"),
        "content": item.get("content", ""),
    }
    if item.get("tool_calls"):
        msg["tool_calls"] = item["tool_calls"]
    if item.get("tool_call_id"):
        msg["tool_call_id"] = item["tool_call_id"]
    if item.get("reasoning_content"):
        msg["reasoning_content"] = item["reasoning_content"]
    return msg


def _assistant_extra(msg):
    """提取需要回传给模型的 assistant 扩展字段"""
    extra = {}
    if getattr(msg, "reasoning_content", None):
        extra["reasoning_content"] = msg.reasoning_content
    return extra


def _format_tool_call(name, args):
    if not args:
        return f"{name}()"

    if name == "read_file":
        path = args.get("path", "")
        start = args.get("start", 1)
        end = args.get("end", 200)
        return f"read_file({path}, {start}-{end})"
    if name == "list_files":
        return f"list_files({args.get('path', '.')})"
    if name == "run_shell":
        return f"run_shell({args.get('command', '')})"
    if name in ("write_file", "replace_in_file", "git_diff"):
        return f"{name}({args.get('path', '')})"
    if name == "apply_patch":
        patches = args.get("patches") or []
        return f"apply_patch({len(patches)} 个补丁)"
    return f"{name}(...)"


def _print_tool_result(result):
    text = str(result)
    if VERBOSE_TOOLS:
        print(f"    结果: {text[:500]}")
        return

    first_line = text.splitlines()[0] if text.splitlines() else ""
    if first_line.startswith("exit_code:"):
        print(f"    完成: {first_line}")
    elif first_line.startswith("错误"):
        print(f"    {first_line}")
    else:
        print(f"    完成: {len(text)} 字符")


def _call_ai(messages):
    """调 API，返回 AssistantMessage"""
    _refresh_system_message(messages)
    messages = trim_messages(messages)
    return backend.chat(messages, tools=TOOLS)


def _call_ai_stream(messages):
    """流式调 API，返回聚合后的 AssistantMessage"""
    _refresh_system_message(messages)
    messages = trim_messages(messages)
    return backend.chat_stream(
        messages,
        tools=TOOLS,
        on_text=lambda text: print(text, end="", flush=True),
    )


def _handle_tool_calls(msg, messages, session_id, max_steps=15):
    """ReAct 循环：反复调工具直到 AI 给出最终回答"""
    step = 0
    while step < max_steps:
        step += 1

        if not msg.tool_calls:
            return msg.content or "", _assistant_extra(msg), msg.streamed

        assistant_msg = {
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        }
        if msg.reasoning_content:
            assistant_msg["reasoning_content"] = msg.reasoning_content
        messages.append(assistant_msg)
        save_message(
            session_id,
            "assistant",
            msg.content or "",
            tool_calls=assistant_msg["tool_calls"],
            reasoning_content=assistant_msg.get("reasoning_content"),
        )

        for tc in msg.tool_calls:
            func_name = tc.name
            try:
                func_args = json.loads(tc.arguments or "{}")
            except json.JSONDecodeError as e:
                result = f"工具参数 JSON 解析失败: {e}"
                print(f"  → {func_name}(参数解析失败)")
                _print_tool_result(result)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
                messages.append(tool_msg)
                save_message(
                    session_id,
                    "tool",
                    result,
                    tool_call_id=tc.id,
                    name=func_name,
                )
                continue

            if VERBOSE_TOOLS:
                print(f"  → {func_name}({json.dumps(func_args, ensure_ascii=False)})")
            else:
                print(f"  → {_format_tool_call(func_name, func_args)}")

            func = FUNC_MAP.get(func_name)
            if not func:
                result = f"未知工具: {func_name}"
            else:
                try:
                    result = func(**func_args)
                except Exception as e:
                    result = f"工具执行失败: {type(e).__name__}: {e}"
            _print_tool_result(result)

            tool_content = str(result).encode("utf-8", errors="replace").decode("utf-8")
            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_content,
            }
            messages.append(tool_msg)
            save_message(
                session_id,
                "tool",
                tool_content,
                tool_call_id=tc.id,
                name=func_name,
            )

        print("AI: ", end="", flush=True)
        msg = _call_ai_stream(messages)
        if msg.streamed:
            print()
        elif not msg.tool_calls and msg.content:
            print(msg.content)

    return msg.content or "(达到最大步骤数)", _assistant_extra(msg), msg.streamed


def chat_loop(session_id):
    """常驻聊天循环"""
    history = load_messages(session_id)

    # 构建 messages：系统指令（含记忆 + 工作区快照）+ 历史消息
    sys_content = _build_system_content()
    messages = [{"role": "system", "content": sys_content}]
    for m in history:
        messages.append(_history_to_message(m))

    print(f"\n进入会话（输入 exit 退出，输入 new 切换会话）\n")

    while True:
        try:
            user_input = input("你: ")
        except KeyboardInterrupt:
            print("\n再见！")
            break

        cmd = user_input.strip().lower()

        if cmd in ("exit", "quit"):
            print("再见！")
            break
        if cmd == "new":
            session_id = create_session()
            print("\n--- 新会话 ---")
            sys_content = _build_system_content()
            messages = [{"role": "system", "content": sys_content}]
            continue
        if cmd in ("list", "sessions"):
            _show_sessions()
            continue
        if not cmd:
            continue

        try:
            if _is_capability_question(user_input):
                full_reply = _capability_answer()
                print(f"AI: {full_reply}")
                save_message(session_id, "user", user_input)
                save_message(session_id, "assistant", full_reply)
                messages.append({"role": "user", "content": user_input})
                messages.append({"role": "assistant", "content": full_reply})
                continue

            # REPL 直执行：!command 或 工具名 参数
            repl = _parse_repl(user_input)
            if repl:
                result = _exec_direct(*repl)
                save_message(session_id, "user", user_input)
                save_message(session_id, "assistant", result)
                continue

            # 走 AI
            save_message(session_id, "user", user_input)
            messages.append({"role": "user", "content": user_input})

            print("AI: ", end="", flush=True)
            msg = _call_ai_stream(messages)

            if msg.tool_calls:
                if msg.streamed:
                    print()
                else:
                    print()
                full_reply, assistant_extra, streamed = _handle_tool_calls(msg, messages, session_id)
            else:
                full_reply = msg.content or ""
                assistant_extra = _assistant_extra(msg)
                streamed = msg.streamed

            if streamed:
                print()
            else:
                print(full_reply)
            save_message(session_id, "assistant", full_reply, **assistant_extra)
            assistant_msg = {"role": "assistant", "content": full_reply}
            assistant_msg.update(assistant_extra)
            messages.append(assistant_msg)

        except KeyboardInterrupt:
            print("\n已取消当前操作，输入 exit 可退出。")
            continue


def _parse_args(argv):
    """解析 CLI 参数"""
    parser = argparse.ArgumentParser(
        prog="mini",
        description="miniAgent 本地 CLI 代码助手",
    )
    parser.add_argument(
        "-c", "--continue",
        dest="continue_last",
        action="store_true",
        help="续接最近一次会话",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示完整工具调用参数和结果片段",
    )
    parser.add_argument(
        "--model",
        help="临时覆盖本次运行使用的模型名",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("sessions", help="列出历史会话")

    resume_parser = subparsers.add_parser("resume", help="按会话 ID 续接")
    resume_parser.add_argument("session_id", help="会话 ID")

    subparsers.add_parser("new", help="创建新会话")

    return parser.parse_args(argv)


def _create_backend_from_args(args):
    """根据 CLI 参数创建模型后端"""
    config = dict(BACKEND)
    if args.model:
        config["model"] = args.model
    return create_backend(config)


def main():
    """入口：mini → 新会话，mini -c → 续接上次会话"""
    global backend, VERBOSE_TOOLS

    args = _parse_args(sys.argv[1:])
    VERBOSE_TOOLS = args.verbose

    if args.command == "sessions":
        _show_sessions()
        return

    backend = _create_backend_from_args(args)

    if args.command == "resume":
        session_id = args.session_id
        _print_header(session_id)
    elif args.continue_last:
        sessions = list_sessions()
        if sessions:
            session_id = sessions[0]["id"]
            _print_header(session_id)
        else:
            print("没有历史会话，创建新会话")
            session_id = create_session()
            _print_header()
    else:
        session_id = create_session()
        _print_header()

    chat_loop(session_id)


if __name__ == "__main__":
    main()
