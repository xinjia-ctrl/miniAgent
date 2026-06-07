"""常驻交互终端：ReAct 工具调用 + 会话管理 + 持久化存档"""

import argparse
import sys
import json
import subprocess
from pathlib import Path
from .models import create_backend
from .runtime import AgentRuntime, assistant_extra
from .config import (
    build_backend_config,
    config_path,
    get_config_value,
    load_user_config,
    set_config_value,
    unset_config_value,
)
from .tools import git_status, git_diff
from .session import (
    create_session, save_message, load_messages,
    list_sessions, get_session, rename_session, delete_session,
)
from .context import trim_messages
from .workspace import get_context
from .audit import log_event, log_tool_call, log_tool_result
from .permissions import (
    PERMISSION_DESCRIPTIONS,
    check_permission as permission_check,
    classify_shell_permission,
    permission_help,
    set_permission_mode,
)
from .prompts import build_system_content, refresh_system_message
from .tool_registry import (
    EDIT_TOOLS,
    PARALLEL_SAFE_TOOLS,
    TOOL_PERMISSIONS,
    TOOLS,
    build_func_map,
    format_tool_call,
    parse_direct_command,
    tools_help as registry_tools_help,
)

try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import Completer, Completion
except ImportError:
    pt_prompt = None
    Completer = object
    Completion = None

backend = None
runtime = None
ACTIVE_BACKEND_CONFIG = build_backend_config()
VERBOSE_TOOLS = False
APPROVE_DIFFS = True
SLASH_COMMANDS = {
    "/": "显示 slash 命令列表",
    "/help": "显示 slash 命令列表",
    "/session": "显示当前会话信息",
    "/session list": "列出历史会话",
    "/session new": "新建并切换会话",
    "/session resume": "切换到指定会话",
    "/session rename": "重命名当前会话",
    "/session delete": "删除会话",
    "/model": "显示当前模型",
    "/model <name>": "临时切换当前模型",
    "/status": "显示 Git 工作区状态",
    "/diff": "显示未暂存 diff",
    "/logs": "显示最近审计日志",
    "/verbose on": "开启详细工具日志",
    "/verbose off": "关闭详细工具日志",
    "/approve on": "开启 diff 审批",
    "/approve off": "关闭 diff 审批",
    "/permission": "显示权限模式",
    "/permission ask": "所有工具操作都询问",
    "/permission auto-read": "自动允许只读操作",
    "/permission trusted": "自动允许非破坏性操作",
    "/tools": "显示可直接调用的工具命令",
    "/exit": "退出会话",
}

# Windows 终端编码兼容（强制 UTF-8 输出）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys, "stdout"):
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)

FUNC_MAP = {}


def _parse_repl(text):
    """解析 REPL 指令，返回 (工具名, 参数字典) 或 None。"""
    return parse_direct_command(text)


def _exec_direct(name, args):
    """直接执行工具并打印结果"""
    return _runtime().exec_direct(name, args)


def _run_tool_function(func_name, func_args):
    return _runtime().run_tool_function(func_name, func_args)


def _run_git(args, input_text=None):
    """执行 git 命令，返回 CompletedProcess"""
    return subprocess.run(
        ["git"] + args,
        cwd=Path.cwd(),
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )


def _classify_shell_permission(command):
    return classify_shell_permission(command)


def _check_permission(name, args, session_id=None):
    return permission_check(name, args, session_id=session_id, tool_permissions=TOOL_PERMISSIONS)


def _git_diff_text():
    result = _run_git(["diff", "--"])
    return result.stdout or ""


def _git_status_short():
    result = _run_git(["status", "--short"])
    return result.stdout.strip()


def _workspace_path(path):
    root = Path.cwd().resolve()
    p = Path(str(path))
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    p.relative_to(root)
    return p


def _paths_for_edit_tool(name, args):
    if name in ("write_file", "replace_in_file"):
        path = args.get("path")
        return [path] if path else []
    if name == "apply_patch":
        paths = []
        for item in args.get("patches") or []:
            if isinstance(item, dict) and item.get("path"):
                paths.append(item["path"])
        return paths
    return []


def _snapshot_paths(paths):
    snapshots = {}
    for path in paths:
        try:
            p = _workspace_path(path)
        except ValueError:
            continue
        if p.exists() and p.is_file():
            snapshots[str(p)] = {
                "exists": True,
                "content": p.read_text(encoding="utf-8", errors="replace"),
            }
        else:
            snapshots[str(p)] = {
                "exists": False,
                "content": "",
            }
    return snapshots


def _restore_snapshot(snapshots):
    for path, item in snapshots.items():
        p = Path(path)
        if item["exists"]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(item["content"], encoding="utf-8")
        elif p.exists() and p.is_file():
            p.unlink()


def _show_diff(diff_text, limit=40000):
    if not diff_text:
        print("\n没有检测到未暂存 diff。")
        return
    print("\n--- 未暂存 diff ---")
    if len(diff_text) > limit:
        print(diff_text[:limit])
        print(f"\n... diff 过长，已截断 {len(diff_text) - limit} 字符")
    else:
        print(diff_text)
    print("--- diff 结束 ---")


def _review_diff_after_edit(session_id, tool_name, before_diff, before_status, snapshots):
    """编辑后展示 diff，并根据用户选择接受或回滚"""
    if not APPROVE_DIFFS:
        return "skipped"

    after_diff = _git_diff_text()
    if after_diff == before_diff:
        return "unchanged"

    _show_diff(after_diff)
    can_revert = not before_status and bool(snapshots)
    if can_revert:
        prompt = "接受这些改动吗？[a]接受 / [r]回滚 / [c]继续修改: "
    else:
        prompt = "接受这些改动吗？[a]接受 / [c]继续修改: "

    while True:
        choice = input(prompt).strip().lower()
        if choice in ("a", "accept", "yes", "y", ""):
            log_event("diff_approval", session_id, tool=tool_name, decision="accepted")
            return "accepted"
        if choice in ("c", "continue"):
            log_event("diff_approval", session_id, tool=tool_name, decision="continue")
            return "continue"
        if choice in ("r", "reject", "rollback"):
            if not can_revert:
                print("当前工作区执行前已有未提交改动，为避免误伤，不支持自动回滚。")
                continue
            _restore_snapshot(snapshots)
            log_event("diff_approval", session_id, tool=tool_name, decision="rolled_back")
            print("已回滚本次编辑工具造成的文件改动。")
            return "rolled_back"
        print("请输入 a、c 或 r。")


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
- `read_many_files 文件1,文件2 [起始行] [结束行]`
- `list_files [目录]`
- `find_files [模式] [目录]`
- `search_text 关键词 [目录]`
- `git_status`
- `git_diff [路径]`
- `delegate 调查任务`
- `!命令` 执行 shell 命令

也可以直接用自然语言说需求，比如“帮我看一下这个项目结构”“给 main.py 加一个参数”“运行测试并修复报错”。"""


def _slash_help():
    return """可用 slash 命令：

/ 或 /help                 显示这份命令列表
/session                  显示当前会话信息
/session list             列出历史会话
/session new              新建会话
/session resume <id>      切换到指定会话
/session rename <title>   重命名当前会话
/session delete [id]      删除会话，默认删除当前会话前会确认
/model                    显示当前模型
/model <name>             临时切换当前模型
/status                   显示 Git 工作区状态
/diff                     显示未暂存 diff
/logs [n]                 显示最近 n 条审计日志
/verbose on|off           开关详细工具日志
/approve on|off           开关编辑后的 diff 审批
/permission               显示当前权限模式
/permission ask           所有工具操作都询问确认
/permission auto-read     自动允许只读操作
/permission trusted       自动允许非破坏性操作
/tools                    显示可直接调用的工具命令
/exit                     退出会话"""


def _tools_help():
    return registry_tools_help()


def _permission_help():
    return permission_help()


class SlashCommandCompleter(Completer):
    """输入 / 时展示本地命令补全。未安装 prompt_toolkit 时不会实例化。"""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        for command, description in SLASH_COMMANDS.items():
            if command.startswith(text):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )


SLASH_COMPLETER = SlashCommandCompleter() if pt_prompt else None


def _read_user_input():
    """读取用户输入；安装 prompt_toolkit 后支持 / 自动补全。"""
    if pt_prompt:
        return pt_prompt(
            "你: ",
            completer=SLASH_COMPLETER,
            complete_while_typing=True,
        )
    return input("你: ")


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
        print(
            f"  {i}. {s['id']}  {s['title']}  "
            f"[{s['message_count']}条]  {s['updated_at']}"
        )


def _show_session_detail(session_id):
    s = get_session(session_id)
    print(f"ID: {s['id']}")
    print(f"标题: {s['title']}")
    print(f"创建时间: {s['created_at']}")
    print(f"更新时间: {s['updated_at']}")
    print(f"消息数: {s['message_count']}")


def _show_audit_logs(limit=20):
    log_dir = Path.cwd() / ".mini" / "logs"
    if not log_dir.exists():
        print("暂无审计日志。")
        return
    files = sorted(log_dir.glob("*.jsonl"), reverse=True)
    if not files:
        print("暂无审计日志。")
        return

    rows = []
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            rows.append(line)
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break

    for line in reversed(rows):
        print(line)


def _mask_secret(key, value):
    if value is None:
        return None
    if "key" not in key.lower() and "token" not in key.lower():
        return value
    text = str(value)
    if len(text) <= 8:
        return "***"
    return text[:4] + "..." + text[-4:]


def _show_config():
    config = load_user_config()
    if not config:
        print("(暂无用户级配置)")
        return
    for key in sorted(config):
        print(f"{key} = {_mask_secret(key, config[key])}")


def _load_session_messages(session_id):
    """加载会话并构建当前 API messages"""
    sys_content = _build_system_content()
    messages = [{"role": "system", "content": sys_content}]
    for item in load_messages(session_id):
        messages.append(_history_to_message(item))
    return messages


def _switch_model(model_name):
    """临时切换当前模型"""
    global backend, ACTIVE_BACKEND_CONFIG
    ACTIVE_BACKEND_CONFIG = dict(ACTIVE_BACKEND_CONFIG)
    ACTIVE_BACKEND_CONFIG["model"] = model_name
    backend = create_backend(ACTIVE_BACKEND_CONFIG)


def _handle_session_slash(parts, session_id, messages):
    """处理 /session 命令，返回 (session_id, messages, should_exit)"""
    if len(parts) == 1:
        _show_session_detail(session_id)
        return session_id, messages, False

    action = parts[1].lower()
    if action in ("list", "ls"):
        _show_sessions()
        return session_id, messages, False

    if action == "new":
        session_id = create_session()
        messages = _load_session_messages(session_id)
        print(f"已创建并切换到新会话: {session_id}")
        log_event("session_switch", session_id=session_id, action="new")
        return session_id, messages, False

    if action == "resume":
        if len(parts) < 3:
            print("用法: /session resume <session_id>")
            return session_id, messages, False
        session_id = parts[2]
        messages = _load_session_messages(session_id)
        print(f"已切换到会话: {session_id}")
        log_event("session_switch", session_id=session_id, action="resume")
        return session_id, messages, False

    if action == "rename":
        if len(parts) < 3:
            print("用法: /session rename <title>")
            return session_id, messages, False
        title = " ".join(parts[2:])
        rename_session(session_id, title)
        print("已重命名当前会话。")
        log_event("session_rename", session_id=session_id, title=title)
        return session_id, messages, False

    if action == "delete":
        target = parts[2] if len(parts) >= 3 else session_id
        answer = input(f"确认删除会话 {target}？输入 yes 确认: ").strip().lower()
        if answer != "yes":
            print("已取消删除。")
            return session_id, messages, False
        try:
            delete_session(target)
            log_event("session_delete", session_id=target)
            print("已删除会话。")
        except OSError as e:
            print(f"删除失败: {e}")
            return session_id, messages, False
        if target == session_id:
            session_id = create_session()
            messages = _load_session_messages(session_id)
            print(f"已自动创建并切换到新会话: {session_id}")
        return session_id, messages, False

    print("未知 /session 命令。输入 /session 查看当前会话，或输入 /help 查看帮助。")
    return session_id, messages, False


def _handle_slash_command(text, session_id, messages):
    """处理 slash command，返回 (handled, session_id, messages, should_exit)"""
    global VERBOSE_TOOLS, APPROVE_DIFFS

    stripped = text.strip()
    if stripped in ("/", "/help"):
        print(_slash_help())
        return True, session_id, messages, False

    parts = stripped.split()
    command = parts[0].lower()

    if command in ("/exit", "/quit"):
        print("再见！")
        return True, session_id, messages, True

    if command == "/tools":
        print(_tools_help())
        return True, session_id, messages, False

    if command == "/session":
        new_session_id, new_messages, should_exit = _handle_session_slash(
            parts,
            session_id,
            messages,
        )
        return True, new_session_id, new_messages, should_exit

    if command == "/model":
        if len(parts) == 1:
            print(f"当前模型: {backend.model}")
            print(f"当前后端: {ACTIVE_BACKEND_CONFIG.get('provider', 'openai')}")
            return True, session_id, messages, False
        model_name = parts[1]
        _switch_model(model_name)
        print(f"已临时切换模型: {model_name}")
        log_event("model_switch", session_id=session_id, model=model_name)
        return True, session_id, messages, False

    if command == "/status":
        print(git_status())
        return True, session_id, messages, False

    if command == "/diff":
        print(git_diff())
        return True, session_id, messages, False

    if command == "/logs":
        limit = 20
        if len(parts) >= 2:
            try:
                limit = int(parts[1])
            except ValueError:
                print("用法: /logs [数量]")
                return True, session_id, messages, False
        _show_audit_logs(limit)
        return True, session_id, messages, False

    if command == "/verbose":
        if len(parts) == 1:
            print(f"详细工具日志: {'on' if VERBOSE_TOOLS else 'off'}")
            return True, session_id, messages, False
        value = parts[1].lower()
        if value not in ("on", "off"):
            print("用法: /verbose on|off")
            return True, session_id, messages, False
        VERBOSE_TOOLS = value == "on"
        print(f"详细工具日志: {'on' if VERBOSE_TOOLS else 'off'}")
        return True, session_id, messages, False

    if command == "/approve":
        if len(parts) == 1:
            print(f"diff 审批: {'on' if APPROVE_DIFFS else 'off'}")
            return True, session_id, messages, False
        value = parts[1].lower()
        if value not in ("on", "off"):
            print("用法: /approve on|off")
            return True, session_id, messages, False
        APPROVE_DIFFS = value == "on"
        print(f"diff 审批: {'on' if APPROVE_DIFFS else 'off'}")
        return True, session_id, messages, False

    if command == "/permission":
        if len(parts) == 1:
            print(_permission_help())
            return True, session_id, messages, False
        mode = parts[1].lower()
        if mode not in PERMISSION_DESCRIPTIONS:
            print("用法: /permission ask|auto-read|trusted")
            return True, session_id, messages, False
        set_permission_mode(mode)
        log_event("permission_mode", session_id=session_id, mode=mode)
        print(f"权限模式已切换为: {mode} - {PERMISSION_DESCRIPTIONS[mode]}")
        return True, session_id, messages, False

    print("未知 slash 命令。输入 / 查看可用命令。")
    return True, session_id, messages, False


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
    return build_system_content()


def _refresh_system_message(messages):
    refresh_system_message(messages)


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
    return assistant_extra(msg)


def _format_tool_call(name, args):
    return format_tool_call(name, args)


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


def _runtime():
    """创建或刷新 Runtime，CLI 只保留交互层职责。"""
    global runtime
    if not FUNC_MAP:
        FUNC_MAP.update(build_func_map(lambda task, max_steps=3: _delegate_task(task, max_steps=max_steps)))
    if runtime is None or runtime.backend is not backend:
        runtime = AgentRuntime(
            backend=backend,
            tools=TOOLS,
            func_map=FUNC_MAP,
            refresh_system_message=_refresh_system_message,
            check_permission=_check_permission,
            log_tool_call=log_tool_call,
            log_tool_result=log_tool_result,
            format_tool_call=_format_tool_call,
            print_tool_result=_print_tool_result,
            git_diff_text=_git_diff_text,
            git_status_short=_git_status_short,
            paths_for_edit_tool=_paths_for_edit_tool,
            snapshot_paths=_snapshot_paths,
            review_diff_after_edit=_review_diff_after_edit,
            edit_tools=EDIT_TOOLS,
            parallel_safe_tools=PARALLEL_SAFE_TOOLS,
            verbose_tools=lambda: VERBOSE_TOOLS,
        )
    return runtime


def _delegate_task(task, max_steps=3):
    """运行一个只读子 agent，用于调查型子任务。"""
    task = str(task or "").strip()
    if not task:
        return "错误：delegate task 不能为空"
    if backend is None:
        return "错误：模型后端尚未初始化，无法 delegate"

    allowed_tools = {
        "read_file",
        "read_many_files",
        "list_files",
        "find_files",
        "search_text",
        "git_status",
        "git_diff",
        "web_fetch",
    }
    child_tools = [
        tool for tool in TOOLS
        if tool.get("function", {}).get("name") in allowed_tools
    ]
    child_funcs = {
        name: func
        for name, func in FUNC_MAP.items()
        if name in allowed_tools
    }
    child_runtime = AgentRuntime(
        backend=backend,
        tools=child_tools,
        func_map=child_funcs,
        refresh_system_message=lambda messages: None,
        check_permission=lambda name, args, session_id=None: (
            name in allowed_tools,
            "allowed" if name in allowed_tools else f"delegate 只允许只读工具: {name}",
        ),
        log_tool_call=lambda session_id, name, args: log_tool_call(session_id, name, args),
        log_tool_result=lambda session_id, name, result: log_tool_result(session_id, name, result),
        print_tool_result=lambda result: None,
        parallel_safe_tools=allowed_tools,
        verbose_tools=lambda: False,
    )

    system = (
        "你是 miniAgent 的只读子 agent。你只能调查、阅读和总结，不能写文件、执行 shell、"
        "修改 Git 或请求用户输入。结论要简洁，必须说明你依据了哪些文件或搜索结果。\n\n"
        + _build_system_content()
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]

    max_steps = max(1, min(int(max_steps), 8))
    for _ in range(max_steps):
        msg = backend.chat(trim_messages(messages), tools=child_tools)
        if not msg.tool_calls:
            return msg.content or "(delegate 没有返回内容)"

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

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.arguments or "{}")
            except json.JSONDecodeError as exc:
                result = f"工具参数 JSON 解析失败: {exc}"
            else:
                if tc.name not in allowed_tools:
                    result = f"delegate 拒绝非只读工具: {tc.name}"
                else:
                    result = child_runtime.run_tool_function(tc.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

    return "delegate 已达到最大步数，未得到最终答案。"


def _call_ai(messages):
    """调 API，返回 AssistantMessage"""
    return _runtime().call_ai(messages)


def _call_ai_stream(messages):
    """流式调 API，返回聚合后的 AssistantMessage"""
    return _runtime().call_ai_stream(messages)


def _handle_tool_calls(msg, messages, session_id, max_steps=15):
    """ReAct 循环：反复调工具直到 AI 给出最终回答"""
    return _runtime().handle_tool_calls(msg, messages, session_id, max_steps=max_steps)


def chat_loop(session_id):
    """常驻聊天循环"""
    messages = _load_session_messages(session_id)

    if pt_prompt:
        print("\n进入会话（输入 / 会自动显示命令，输入 exit 退出）\n")
    else:
        print("\n进入会话（输入 / 回车查看命令，输入 exit 退出）\n")

    while True:
        try:
            user_input = _read_user_input()
        except KeyboardInterrupt:
            print("\n再见！")
            break

        cmd = user_input.strip().lower()

        if cmd in ("exit", "quit"):
            print("再见！")
            break
        if cmd.startswith("/"):
            handled, session_id, messages, should_exit = _handle_slash_command(
                user_input,
                session_id,
                messages,
            )
            if should_exit:
                break
            if handled:
                continue
        if cmd == "new":
            session_id = create_session()
            print("\n--- 新会话 ---")
            messages = _load_session_messages(session_id)
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
    parser.epilog = (
        "大上下文可用环境变量调整："
        "MINI_CONTEXT_BUDGET、MINI_PREFIX_BUDGET、MINI_HISTORY_BUDGET、"
        "MINI_DOC_CHAR_LIMIT、MINI_INSTRUCTION_CHAR_LIMIT。"
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("sessions", help="列出历史会话")

    resume_parser = subparsers.add_parser("resume", help="按会话 ID 续接")
    resume_parser.add_argument("session_id", help="会话 ID")

    subparsers.add_parser("new", help="创建新会话")

    show_parser = subparsers.add_parser("show", help="查看会话元信息")
    show_parser.add_argument("session_id", help="会话 ID")

    rename_parser = subparsers.add_parser("rename", help="重命名会话")
    rename_parser.add_argument("session_id", help="会话 ID")
    rename_parser.add_argument("title", help="新标题")

    delete_parser = subparsers.add_parser("delete", help="删除会话")
    delete_parser.add_argument("session_id", help="会话 ID")
    delete_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="跳过删除确认",
    )

    logs_parser = subparsers.add_parser("logs", help="查看最近审计日志")
    logs_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="显示最近多少条日志",
    )

    config_parser = subparsers.add_parser("config", help="管理用户级配置")
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    config_subparsers.add_parser("list", help="列出当前用户级配置")
    config_subparsers.add_parser("path", help="显示配置文件路径")

    config_get = config_subparsers.add_parser("get", help="读取配置项")
    config_get.add_argument("key", help="配置键")

    config_set = config_subparsers.add_parser("set", help="写入配置项")
    config_set.add_argument("key", help="配置键")
    config_set.add_argument("value", help="配置值")

    config_unset = config_subparsers.add_parser("unset", help="删除配置项")
    config_unset.add_argument("key", help="配置键")

    return parser.parse_args(argv)


def _create_backend_from_args(args):
    """根据 CLI 参数创建模型后端"""
    global ACTIVE_BACKEND_CONFIG
    overrides = {"model": args.model}
    config = build_backend_config(overrides)
    ACTIVE_BACKEND_CONFIG = dict(config)
    return create_backend(config)


def main():
    """入口：mini → 新会话，mini -c → 续接上次会话"""
    global backend, VERBOSE_TOOLS

    args = _parse_args(sys.argv[1:])
    VERBOSE_TOOLS = args.verbose

    if args.command == "sessions":
        _show_sessions()
        return

    if args.command == "show":
        _show_session_detail(args.session_id)
        return

    if args.command == "rename":
        rename_session(args.session_id, args.title)
        log_event("session_rename", session_id=args.session_id, title=args.title)
        print("已重命名会话。")
        return

    if args.command == "delete":
        if not args.yes:
            answer = input(f"确认删除会话 {args.session_id}？输入 yes 确认: ").strip().lower()
            if answer != "yes":
                print("已取消删除。")
                return
        try:
            delete_session(args.session_id)
            log_event("session_delete", session_id=args.session_id)
            print("已删除会话。")
        except OSError as e:
            print(f"删除失败: {e}")
        return

    if args.command == "logs":
        _show_audit_logs(args.limit)
        return

    if args.command == "config":
        if args.config_command in (None, "list"):
            _show_config()
            return
        if args.config_command == "path":
            print(config_path())
            return
        if args.config_command == "get":
            value = get_config_value(args.key)
            if value is None:
                print("(未设置)")
            else:
                print(_mask_secret(args.key, value))
            return
        if args.config_command == "set":
            set_config_value(args.key, args.value)
            shown = _mask_secret(args.key, args.value)
            print(f"已设置 {args.key} = {shown}")
            return
        if args.config_command == "unset":
            existed = unset_config_value(args.key)
            print("已删除配置项。" if existed else "配置项不存在。")
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
