# workspace.py - 阶段七
# 工作区快照：采集仓库状态并计算指纹

import locale
import subprocess
import hashlib
import json
import os
from pathlib import Path

_ENCODING = locale.getpreferredencoding()
DOC_CHAR_LIMIT = int(os.getenv("MINI_DOC_CHAR_LIMIT", "20000"))
INSTRUCTION_CHAR_LIMIT = int(os.getenv("MINI_INSTRUCTION_CHAR_LIMIT", "30000"))

# 项目文档白名单（这些文档会自动注入 prompt）
DOC_NAMES = ("README.md", "pyproject.toml")

# 项目指令文件，后面的优先级更高
INSTRUCTION_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    ".mini/instructions.md",
)


class WorkspaceContext:
    """工作区上下文：采集仓库状态

    每次构建 prompt 前，检查工作区指纹是否变化。
    如果变了，说明有人改了代码、提交了新 commit，需要重建 prompt。
    """

    def __init__(self, cwd):
        self.cwd = Path(cwd).resolve()
        self.repo_root = self._find_repo_root()
        self.refresh()

    def _find_repo_root(self):
        """找到 git 仓库根目录"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=self.cwd, capture_output=True, timeout=5,
            )
            return Path(result.stdout.decode("utf-8", errors="replace").strip()).resolve()
        except Exception:
            return self.cwd

    def _git(self, args):
        """执行 git 命令，失败时返回空字符串"""
        try:
            result = subprocess.run(
                ["git"] + args, cwd=self.cwd,
                capture_output=True, timeout=5,
            )
            raw = result.stdout
            # git 输出可能是 GBK 或 UTF-8，自动检测
            if raw:
                try:
                    return raw.decode("utf-8").strip()
                except UnicodeDecodeError:
                    return raw.decode(_ENCODING, errors="replace").strip()
            return ""
        except Exception:
            return ""

    def refresh(self):
        """刷新工作区快照"""
        self.branch = self._git(["branch", "--show-current"]) or "-"
        self.status = self._git(["status", "--short"]) or "clean"
        self.recent_commits = [
            line for line in self._git(["log", "--oneline", "-5"]).splitlines() if line
        ]
        # 读取项目文档
        self.project_docs = {}
        for name in DOC_NAMES:
            path = self.repo_root / name
            if path.exists():
                self.project_docs[name] = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[:DOC_CHAR_LIMIT]

        # 读取项目指令
        self.project_instructions = {}
        for name in INSTRUCTION_FILES:
            path = self.repo_root / name
            if path.exists() and path.is_file():
                self.project_instructions[name] = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[:INSTRUCTION_CHAR_LIMIT]

    def fingerprint(self):
        """计算工作区指纹

        如果 git status、分支、最近提交、文档内容任何一项变了，
        指纹就会变化，prompt 就需要重建。
        """
        payload = {
            "cwd": str(self.cwd),
            "repo_root": str(self.repo_root),
            "branch": self.branch,
            "status": self.status,
            "commits": list(self.recent_commits),
            "docs": dict(self.project_docs),
            "instructions": dict(self.project_instructions),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def text(self):
        """渲染工作区文本，注入 prompt"""
        commits = "\n".join(f"- {c}" for c in self.recent_commits) or "- 无"
        docs = "\n".join(
            f"- {name}\n{content}" for name, content in self.project_docs.items()
        ) or "- 无"
        instructions = "\n".join(
            f"- {name}\n{content}" for name, content in self.project_instructions.items()
        ) or "- 无"

        return f"""工作区状态：
- 目录：{self.cwd}
- 仓库：{self.repo_root}
- 分支：{self.branch}
- 未提交变更：
{self.status}
- 最近提交：
{commits}
- 项目指令：
{instructions}
- 项目文档：
{docs}"""


# 全局单例：供 tools.py 和 main.py 导入使用
_ws_instance = None


def get_context(cwd=None):
    """获取或创建工作区上下文（全局唯一）"""
    global _ws_instance
    if _ws_instance is None or (cwd and _ws_instance.cwd != Path(cwd).resolve()):
        _ws_instance = WorkspaceContext(cwd or Path.cwd())
    return _ws_instance


# 兼容 tools.py 的 ROOT 导入
ROOT = Path.cwd().resolve()
