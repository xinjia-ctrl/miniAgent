"""权限分级与 shell 命令分类。"""

from __future__ import annotations

import json
import re

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


def set_permission_mode(mode: str) -> None:
    global PERMISSION_MODE
    if mode not in PERMISSION_DESCRIPTIONS:
        raise ValueError("未知权限模式")
    PERMISSION_MODE = mode


def get_permission_mode() -> str:
    return PERMISSION_MODE


def classify_shell_permission(command):
    """按命令内容细分 shell 权限等级。"""
    low = str(command).strip().lower()

    destructive_patterns = (
        r"\brm\b",
        r"\bdel\b",
        r"\berase\b",
        r"\brmdir\b",
        r"\bremove-item\b",
        r"\bformat\b",
        r"\bshutdown\b",
        r"\bgit\s+reset\b",
        r"\bgit\s+clean\b",
        r"\bgit\s+checkout\b",
        r"\bgit\s+restore\b",
        r"\bgit\s+rebase\b",
    )
    if any(re.search(pattern, low) for pattern in destructive_patterns):
        return "destructive"

    network_patterns = (
        r"\bpip\s+install\b",
        r"\buv\s+pip\s+install\b",
        r"\bnpm\s+install\b",
        r"\bpnpm\s+install\b",
        r"\byarn\s+add\b",
        r"\byarn\s+install\b",
        r"\bcurl\b",
        r"\bwget\b",
        r"\bgit\s+pull\b",
        r"\bgit\s+push\b",
        r"\bgit\s+fetch\b",
        r"\bgit\s+clone\b",
        r"\bgh\s+",
    )
    if any(re.search(pattern, low) for pattern in network_patterns):
        return "network"

    git_write_patterns = (
        r"\bgit\s+add\b",
        r"\bgit\s+commit\b",
        r"\bgit\s+merge\b",
        r"\bgit\s+branch\b",
        r"\bgit\s+tag\b",
    )
    if any(re.search(pattern, low) for pattern in git_write_patterns):
        return "git-write"

    workspace_write_patterns = (
        r">",
        r">>",
        r"\bcopy\b",
        r"\bmove\b",
        r"\bren\b",
        r"\brename-item\b",
        r"\bnew-item\b",
        r"\bset-content\b",
        r"\badd-content\b",
        r"\bout-file\b",
        r"\btouch\b",
        r"\bmkdir\b",
        r"\bmd\b",
        r"\bpython\s+-c\b",
        r"\bpy\s+-c\b",
    )
    if any(re.search(pattern, low) for pattern in workspace_write_patterns):
        return "workspace-write"

    git_read_patterns = (
        r"^git\s+status\b",
        r"^git\s+diff\b",
        r"^git\s+log\b",
        r"^git\s+show\b",
        r"^git\s+branch\b.*(--show-current|-v|--list)?$",
    )
    if any(re.search(pattern, low) for pattern in git_read_patterns):
        return "read-only"

    read_only_patterns = (
        r"^dir\b",
        r"^type\b",
        r"^findstr\b",
        r"^rg\b",
        r"^python\s+.*(--help|-h)\b",
        r"^py\s+.*(--help|-h)\b",
    )
    if any(re.search(pattern, low) for pattern in read_only_patterns):
        return "read-only"

    return "shell-write"


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
