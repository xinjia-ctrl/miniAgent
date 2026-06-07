"""权限分级与 shell 命令分类。"""

from __future__ import annotations

import dataclasses
import json
import shlex

from .audit import log_event

PERMISSION_MODE = "auto-read"
PERMISSION_LEVELS = (
    "read-only",
    "workspace-write",
    "shell-write",
    "network",
    "git-write",
    "destructive",
)
PERMISSION_DESCRIPTIONS = {
    "ask": "所有工具操作都询问确认",
    "auto-read": "自动允许只读操作，写入和命令类操作询问确认",
    "trusted": "自动允许非破坏性操作，破坏性操作仍询问确认",
}

PERMISSION_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "shell-write": 2,
    "network": 3,
    "git-write": 4,
    "destructive": 5,
}

SHELL_OPERATORS = {"|", "&&", "||", ";", ">", ">>", "<", "&"}
SHELL_OPERATOR_CHARS = ("|", ";", ">", "<", "&")
REDIRECTION_OPERATOR_CHARS = (">", "<")
CMD_BUILTINS = {"dir", "type", "findstr", "echo"}
SHELL_INTERPRETERS = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}


@dataclasses.dataclass(frozen=True)
class ShellCommandAnalysis:
    command: str
    tokens: list[str]
    level: str
    unsupported_reason: str = ""
    requires_cmd_builtin: bool = False

    @property
    def supported(self) -> bool:
        return not self.unsupported_reason


def set_permission_mode(mode: str) -> None:
    global PERMISSION_MODE
    if mode not in PERMISSION_DESCRIPTIONS:
        raise ValueError("未知权限模式")
    PERMISSION_MODE = mode


def get_permission_mode() -> str:
    return PERMISSION_MODE


def _max_permission(levels):
    return max(levels, key=lambda item: PERMISSION_RANK.get(item, 2))


def _split_command(command):
    try:
        return shlex.split(str(command or ""), posix=False)
    except ValueError:
        return []


def _command_name(tokens):
    if not tokens:
        return ""
    return tokens[0].lower().removesuffix(".exe")


def _contains_operator(tokens):
    return any(
        token.lower() in SHELL_OPERATORS
        or any(char in token for char in SHELL_OPERATOR_CHARS)
        for token in tokens
    )


def _contains_redirection(tokens):
    return any(any(char in token for char in REDIRECTION_OPERATOR_CHARS) for token in tokens)


def _is_git(tokens, subcommand):
    return len(tokens) >= 2 and _command_name(tokens) == "git" and tokens[1].lower() == subcommand


def _classify_tokens(tokens):
    if not tokens:
        return "shell-write"

    lower = [token.lower() for token in tokens]
    name = _command_name(tokens)

    if _contains_redirection(tokens):
        return "workspace-write"

    if name in {"rm", "del", "erase", "rmdir", "remove-item", "ri", "rd", "format", "shutdown"}:
        return "destructive"
    if name == "reg" and len(lower) >= 2 and lower[1] == "delete":
        return "destructive"
    if _is_git(tokens, "reset") or _is_git(tokens, "clean") or _is_git(tokens, "checkout"):
        return "destructive"
    if _is_git(tokens, "restore") or _is_git(tokens, "rebase"):
        return "destructive"

    if _is_git(tokens, "status") or _is_git(tokens, "diff"):
        return "read-only"
    if _is_git(tokens, "log") or _is_git(tokens, "show"):
        return "read-only"
    if _is_git(tokens, "branch"):
        branch_args = set(lower[2:])
        if not branch_args or branch_args <= {"--show-current", "-v", "--list"}:
            return "read-only"

    if name in {"curl", "wget", "gh"}:
        return "network"
    if _is_git(tokens, "pull") or _is_git(tokens, "push"):
        return "network"
    if _is_git(tokens, "fetch") or _is_git(tokens, "clone"):
        return "network"
    if name in {"pip", "pip3"} and len(lower) >= 2 and lower[1] == "install":
        return "network"
    if name in {"python", "py"} and lower[1:4] in (["-m", "pip", "install"], ["-m", "pip3", "install"]):
        return "network"
    if name == "uv" and lower[1:3] == ["pip", "install"]:
        return "network"
    if name in {"npm", "pnpm"} and len(lower) >= 2 and lower[1] == "install":
        return "network"
    if name == "yarn" and len(lower) >= 2 and lower[1] in {"add", "install"}:
        return "network"

    if _is_git(tokens, "add") or _is_git(tokens, "commit") or _is_git(tokens, "merge"):
        return "git-write"
    if _is_git(tokens, "branch") or _is_git(tokens, "tag"):
        return "git-write"

    if name in {
        "copy",
        "move",
        "ren",
        "rename-item",
        "new-item",
        "set-content",
        "add-content",
        "out-file",
        "touch",
        "mkdir",
        "md",
    }:
        return "workspace-write"
    if name in {"python", "py"} and "-c" in lower:
        return "workspace-write"

    if name in {"dir", "type", "findstr", "rg"}:
        return "read-only"
    if name in {"python", "py"} and any(arg in {"--help", "-h"} for arg in lower[1:]):
        return "read-only"

    return "shell-write"


def analyze_shell_command(command):
    """解析 shell 命令，给权限门禁和执行层共享同一份判断结果。"""
    command_text = str(command or "").strip()
    tokens = _split_command(command_text)
    if not command_text:
        return ShellCommandAnalysis(command_text, [], "shell-write", "命令不能为空")
    if not tokens:
        return ShellCommandAnalysis(command_text, [], "shell-write", "命令解析失败")

    levels = [_classify_tokens(tokens)]
    if _contains_operator(tokens):
        levels.append("workspace-write" if _contains_redirection(tokens) else "shell-write")

    name = _command_name(tokens)
    unsupported_reason = ""
    requires_cmd_builtin = name in CMD_BUILTINS
    if _contains_operator(tokens):
        unsupported_reason = "run_shell 不支持管道、重定向或命令串联，请使用专用工具或单条命令"
    elif name in SHELL_INTERPRETERS:
        unsupported_reason = "run_shell 不支持嵌套 shell 解释器"

    return ShellCommandAnalysis(
        command=command_text,
        tokens=tokens,
        level=_max_permission(levels),
        unsupported_reason=unsupported_reason,
        requires_cmd_builtin=requires_cmd_builtin,
    )


def classify_shell_permission(command):
    """按命令内容细分 shell 权限等级。"""
    return analyze_shell_command(command).level


def permission_for_tool(name, args, tool_permissions):
    if name == "run_shell":
        return classify_shell_permission((args or {}).get("command", ""))
    return tool_permissions.get(name, "shell-write")


def permission_allowed(level):
    if PERMISSION_MODE == "ask":
        return False
    if PERMISSION_MODE == "auto-read":
        return level == "read-only"
    if PERMISSION_MODE == "trusted":
        return level != "destructive"
    return False


def check_permission(name, args, session_id=None, tool_permissions=None, input_func=input):
    """工具执行前的权限门禁，返回 (allowed, reason)。"""
    level = permission_for_tool(name, args, tool_permissions or {})
    if permission_allowed(level):
        return True, "allowed"

    print(f"\n权限请求: {name} 需要 {level} 权限")
    print(f"当前模式: {PERMISSION_MODE} - {PERMISSION_DESCRIPTIONS.get(PERMISSION_MODE, '')}")
    if name == "run_shell":
        print(f"命令: {(args or {}).get('command', '')}")
    elif args:
        preview = json.dumps(args, ensure_ascii=False)
        print(f"参数: {preview[:500]}")

    answer = input_func("允许执行？[y]允许 / [n]拒绝: ").strip().lower()
    decision = "allowed" if answer in ("y", "yes", "a", "allow") else "denied"
    log_event(
        "permission_decision",
        session_id=session_id,
        tool=name,
        level=level,
        mode=PERMISSION_MODE,
        decision=decision,
    )
    if decision == "allowed":
        return True, "allowed"
    return False, f"权限拒绝: {name} 需要 {level} 权限"


def permission_help():
    lines = [
        f"当前权限模式: {PERMISSION_MODE}",
        "",
        "权限等级:",
    ]
    lines.extend(f"- {level}" for level in PERMISSION_LEVELS)
    lines.extend(["", "模式:"])
    lines.extend(f"- {mode}: {desc}" for mode, desc in PERMISSION_DESCRIPTIONS.items())
    lines.extend(["", "用法:", "/permission ask", "/permission auto-read", "/permission trusted"])
    return "\n".join(lines)
