"""常驻交互终端：ReAct 工具调用 + 会话管理 + 持久化存档"""

import sys
import json
from openai import OpenAI
from config import DEEPSEEK_API_KEY
from tools import read_file, list_files, run_shell
from session import (
    create_session, save_message, load_messages,
    list_sessions, get_session, rename_session, delete_session,
)
from context import trim_messages
from memory import remember, forget as forget_memory, build_memory_block
from workspace import get_context

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

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
            "description": "执行 shell 命令",
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
    "remember": remember,
    "forget_memory": forget_memory,
}

SYSTEM_PROMPT = """你是一个可以操作电脑的 AI 智能体。你有以下能力：
- read_file: 读取文件
- list_files: 列出目录
- run_shell: 执行 shell 命令
- remember: 记住信息（跨会话保留，对话结束也不会丢）
- forget_memory: 删除已记住的信息

请按 ReAct 模式工作：
1. 思考当前任务需要做什么（Thought）
2. 调用合适的工具（Action）
3. 观察工具返回的结果（Observation）
4. 重复直到任务完成，然后给出最终答案

注意：你可以连续多次调用工具，不需要一次只调一个。
重要：当前系统是 Windows（不是 Linux/Mac），run_shell 中请使用 Windows 命令（dir、type、findstr 等），不要用 find、grep、xargs、wc 等 Linux 命令。"""


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
    model = "deepseek-v4-flash"
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


def _call_ai(messages):
    """调 API，返回 message 对象"""
    messages = trim_messages(messages)
    return client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=_clean(messages),
        tools=TOOLS,
        stream=False,
    ).choices[0].message


def _handle_tool_calls(msg, messages, session_id, max_steps=15):
    """ReAct 循环：反复调工具直到 AI 给出最终回答"""
    step = 0
    while step < max_steps:
        step += 1

        if not msg.tool_calls:
            return msg.content or ""

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            func_name = tc.function.name
            func_args = json.loads(tc.function.arguments)
            print(f"  → {func_name}({json.dumps(func_args, ensure_ascii=False)})")

            func = FUNC_MAP.get(func_name)
            result = func(**func_args) if func else f"未知工具: {func_name}"
            print(f"    结果: {str(result)[:200]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result).encode("utf-8", errors="replace").decode("utf-8"),
            })

        msg = _call_ai(messages)

    return msg.content or "(达到最大步骤数)"


def chat_loop(session_id):
    """常驻聊天循环"""
    history = load_messages(session_id)

    # 构建 messages：系统指令（含记忆 + 工作区快照）+ 历史消息
    ws = get_context()
    ws_text = ws.text()
    mem_block = build_memory_block()
    extra = "\n\n".join(filter(None, [ws_text, mem_block]))
    sys_content = SYSTEM_PROMPT + ("\n\n" + extra if extra else "")
    messages = [{"role": "system", "content": sys_content}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    print(f"\n进入会话（输入 exit 退出，输入 new 切换会话）\n")

    while True:
        try:
            user_input = input("你: ")
            cmd = user_input.strip().lower()

            if cmd in ("exit", "quit"):
                print("再见！")
                break
            if cmd == "new":
                session_id = create_session()
                print("\n--- 新会话 ---")
                messages = [{"role": "system", "content": sys_content}]
                continue
            if cmd == "list":
                _show_sessions()
                continue
            if not cmd:
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
            msg = _call_ai(messages)

            if msg.tool_calls:
                full_reply = _handle_tool_calls(msg, messages, session_id)
            else:
                full_reply = msg.content or ""

            print(full_reply)
            save_message(session_id, "assistant", full_reply)
            messages.append({"role": "assistant", "content": full_reply})

        except KeyboardInterrupt:
            print("\n再见！")
            break


def main():
    """入口：mini → 新会话，mini -c → 续接上次会话"""
    if "-c" in sys.argv:
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
