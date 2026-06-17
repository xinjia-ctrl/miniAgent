from __future__ import annotations

import re
import shlex
from enum import Enum


class ShellRisk(str, Enum):
    read_only = "read_only"
    test_build = "test_build"
    workspace_write = "workspace_write"
    git_write = "git_write"
    network = "network"
    dangerous = "dangerous"
    unknown = "unknown"


class ShellClassification:
    def __init__(self, risk: ShellRisk, reason: str):
        self.risk = risk
        self.reason = reason

    @property
    def is_dangerous(self) -> bool:
        return self.risk is ShellRisk.dangerous


def classify_shell_command(command: str) -> ShellClassification:
    normalized = re.sub(r"\s+", " ", command.strip())
    lowered = normalized.lower()
    if not lowered:
        return ShellClassification(ShellRisk.unknown, "空 shell 命令")

    if _matches_any(
        lowered,
        [
            r"\bremove-item\b.*-recurse\b",
            r"\brm\b.*\b-rf\b",
            r"\bdel\b",
            r"\brmdir\b",
            r"\brd\b",
            r"\bformat\b",
            r"\bdiskpart\b",
            r"\bcipher\b",
            r"\bshutdown\b",
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+clean\b",
        ],
    ):
        return ShellClassification(ShellRisk.dangerous, "危险 shell 命令")

    argv = _split_command(normalized)
    executable = argv[0].lower() if argv else ""
    first_two = " ".join(item.lower() for item in argv[:2])

    if executable in {"rg", "grep", "findstr", "type", "cat"}:
        return ShellClassification(ShellRisk.read_only, "只读搜索或查看命令")
    if executable in {"get-childitem", "get-content", "select-string"}:
        return ShellClassification(ShellRisk.read_only, "PowerShell 只读命令")
    if first_two in {"git status", "git diff", "git log", "git show"}:
        return ShellClassification(ShellRisk.read_only, "只读 git 命令")

    if _matches_any(
        lowered,
        [
            r"^pytest(\s|$)",
            r"^ruff\s+check(\s|$)",
            r"^npm\s+test(\s|$)",
            r"^mvn\s+test(\s|$)",
            r"^cargo\s+test(\s|$)",
            r"^python\s+-m\s+pytest(\s|$)",
        ],
    ):
        return ShellClassification(ShellRisk.test_build, "测试或构建命令")

    if executable in {"new-item", "set-content", "copy-item", "move-item"}:
        return ShellClassification(ShellRisk.workspace_write, "工作区写入命令")
    if first_two in {"git add", "git commit", "git branch", "git switch", "git merge"}:
        return ShellClassification(ShellRisk.git_write, "Git 写操作")
    if executable in {"curl", "wget", "invoke-webrequest", "iwr"}:
        return ShellClassification(ShellRisk.network, "网络访问命令")
    if first_two in {"pip install", "npm install", "pnpm install", "yarn add"}:
        return ShellClassification(ShellRisk.network, "依赖下载命令")

    return ShellClassification(ShellRisk.unknown, "未知 shell 命令")


def is_dangerous_shell_command(command: str) -> bool:
    return classify_shell_command(command).is_dangerous


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return command.split()


def _matches_any(value: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, value) for pattern in patterns)
