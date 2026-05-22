# tools.py - 阶段一
# 工具函数：AI 通过调用这些函数来操作你的电脑

import locale
import re
import subprocess
from pathlib import Path

from .workspace import ROOT
# 使用系统编码（Windows 上通常是 gbk）
_ENCODING = locale.getpreferredencoding()
_ROOT = ROOT.resolve()

_DANGEROUS_COMMANDS = (
    r"\brm\b",
    r"\bdel\b",
    r"\berase\b",
    r"\brmdir\b",
    r"\bRemove-Item\b",
    r"\bri\b",
    r"\brd\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\breg\s+delete\b",
    r"\bgit\s+reset\b",
    r"\bgit\s+clean\b",
    r"\bgit\s+checkout\b",
)

def _check_path(path):
    """安全校验：确保路径不逃逸出工作区

    这是 miniAgent 最重要的安全机制之一。
    如果 AI 试图读 /etc/passwd 或 ../secret.txt，这里会拦截。
    """
    p = Path(str(path))
    if not p.is_absolute():
        p = _ROOT / p
    p = p.resolve()
    try:
        p.relative_to(_ROOT)
    except ValueError:
        raise ValueError(f"路径逃逸: {path}")
    return p


def _rel_path(path):
    """返回相对工作区路径，供 git 命令使用"""
    return str(_check_path(path).relative_to(_ROOT))


def _run(args, timeout=20):
    """执行不经过 shell 的命令，避免命令注入"""
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            encoding=_ENCODING,
            errors="replace",
            timeout=timeout,
            cwd=_ROOT,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return f"exit_code: {result.returncode}\nstdout:\n{stdout.strip()}\nstderr:\n{stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"exit_code: -1\nstdout:\n\nstderr:\n命令超时 ({timeout}s)"
    except Exception as e:
        return f"exit_code: -1\nstdout:\n\nstderr:\n{str(e)}"


def _is_dangerous_command(command):
    """粗粒度识别会删除、覆盖历史或影响系统的命令"""
    return any(re.search(pattern, command, re.IGNORECASE) for pattern in _DANGEROUS_COMMANDS)


def _confirm_dangerous(command):
    """危险命令执行前让用户确认"""
    print("\n检测到危险命令，可能删除文件、重写 Git 历史或影响系统。")
    print(f"命令: {command}")
    answer = input("确认执行请输入 yes: ").strip().lower()
    return answer == "yes"

def read_file(path, start=1, end=1000):
    """读取文件内容（按行号范围）"""
    p = _check_path(path)
    if not p.is_file():
        return f"错误：文件不存在 {path}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    # 按行号范围截取
    body = "\n".join(
        f"{i+1}: {line}" for i, line in enumerate(lines[start-1:end], start=start)
    )
    return f"# {path}\n{body}"

def list_files(path="."):
    """列出目录内容"""
    p = _check_path(path)
    if not p.exists():
        return f"错误：目录不存在 {path}"
    if not p.is_dir():
        return f"错误：不是目录 {path}"
    items = []
    for item in sorted(p.iterdir()):
        kind = "[D]" if item.is_dir() else "[F]"
        items.append(f"{kind} {item.name}")
    return "\n".join(items) if items else "(空目录)"


def write_file(path, content, overwrite=False, create_dirs=False):
    """写入文件。默认不覆盖已有文件，避免误删内容。"""
    p = _check_path(path)
    if p.exists() and not overwrite:
        return f"错误：文件已存在，如需覆盖请设置 overwrite=true：{path}"
    if not p.parent.exists():
        if not create_dirs:
            return f"错误：父目录不存在，如需创建目录请设置 create_dirs=true：{p.parent}"
        p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not p.is_file():
        return f"错误：目标不是普通文件 {path}"
    p.write_text(str(content), encoding="utf-8")
    return f"已写入 {path} ({len(str(content))} 字符)"


def replace_in_file(path, old_text, new_text, expected_replacements=1):
    """在文件中做精确文本替换。默认要求只替换 1 处。"""
    p = _check_path(path)
    if not p.is_file():
        return f"错误：文件不存在 {path}"

    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_text)
    if count == 0:
        return "错误：未找到 old_text，未修改文件"
    if expected_replacements is not None and count != int(expected_replacements):
        return (
            f"错误：old_text 出现 {count} 次，期望 {expected_replacements} 次，"
            "为避免误替换未修改文件"
        )

    p.write_text(text.replace(old_text, new_text), encoding="utf-8")
    return f"已修改 {path}，替换 {count} 处"


def apply_patch(patches):
    """批量应用精确替换补丁。

    patches 格式：
    [
      {"path": "main.py", "old_text": "...", "new_text": "...", "expected_replacements": 1}
    ]
    """
    if not isinstance(patches, list) or not patches:
        return "错误：patches 必须是非空列表"

    prepared = []
    for i, patch in enumerate(patches, 1):
        if not isinstance(patch, dict):
            return f"错误：第 {i} 个 patch 不是对象"
        path = patch.get("path")
        old_text = patch.get("old_text")
        new_text = patch.get("new_text")
        expected = patch.get("expected_replacements", 1)
        if not path or old_text is None or new_text is None:
            return f"错误：第 {i} 个 patch 必须包含 path、old_text、new_text"

        p = _check_path(path)
        if not p.is_file():
            return f"错误：文件不存在 {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_text)
        if count == 0:
            return f"错误：第 {i} 个 patch 未找到 old_text，未修改任何文件"
        if expected is not None and count != int(expected):
            return (
                f"错误：第 {i} 个 patch 的 old_text 出现 {count} 次，"
                f"期望 {expected} 次，未修改任何文件"
            )
        prepared.append((p, text.replace(old_text, new_text), path, count))

    for p, new_text, _, _ in prepared:
        p.write_text(new_text, encoding="utf-8")

    lines = [f"已应用 {len(prepared)} 个 patch"]
    lines.extend(f"- {path}: 替换 {count} 处" for _, _, path, count in prepared)
    return "\n".join(lines)


def git_status():
    """查看 Git 工作区状态"""
    return _run(["git", "status", "--short", "--branch"])


def git_diff(path=None):
    """查看未暂存 diff，可选限制到单个工作区内路径"""
    args = ["git", "diff"]
    if path:
        args.extend(["--", _rel_path(path)])
    return _run(args)

def run_shell(command, timeout=20):
    """执行 shell 命令（危险的！）"""
    if _is_dangerous_command(command) and not _confirm_dangerous(command):
        return "exit_code: -1\nstdout:\n\nstderr:\n用户取消执行危险命令"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding=_ENCODING,
            errors="replace",
            timeout=timeout,
            cwd=_ROOT,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return f"exit_code: {result.returncode}\nstdout:\n{stdout.strip()}\nstderr:\n{stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"exit_code: -1\nstdout:\n\nstderr:\n命令超时 ({timeout}s)"
    except Exception as e:
        return f"exit_code: -1\nstdout:\n\nstderr:\n{str(e)}"
