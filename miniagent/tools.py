# tools.py - 阶段一
# 工具函数：AI 通过调用这些函数来操作你的电脑

import locale
import re
import shutil
import subprocess
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .security import shell_env
from .workspace import ROOT
# 使用系统编码（Windows 上通常是 gbk）
_ENCODING = locale.getpreferredencoding()
_ROOT = ROOT.resolve()
_IGNORED_NAMES = {
    ".git",
    ".idea",
    ".mini",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
}

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


def _read_text_file(path):
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise ValueError(f"拒绝处理疑似二进制文件: {path.relative_to(_ROOT)}")
    return data.decode("utf-8", errors="replace")


def _write_text_file(path, text):
    path.write_text(str(text), encoding="utf-8")


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
            env=shell_env(cwd=_ROOT),
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
    lines = _read_text_file(p).splitlines()
    # 按行号范围截取
    body = "\n".join(
        f"{i}: {line}" for i, line in enumerate(lines[start-1:end], start=start)
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


def find_files(pattern="*", path=".", max_results=200):
    """按文件名模式查找文件，自动跳过常见缓存和依赖目录。"""
    base = _check_path(path)
    if not base.exists():
        return f"错误：路径不存在 {path}"
    if not base.is_dir():
        return f"错误：不是目录 {path}"

    pattern = str(pattern or "*")
    max_results = max(1, min(int(max_results), 1000))
    matches = []
    for item in base.rglob(pattern):
        try:
            rel = item.relative_to(_ROOT)
        except ValueError:
            continue
        if any(part in _IGNORED_NAMES for part in rel.parts):
            continue
        if item.is_file():
            matches.append(str(rel))
        if len(matches) >= max_results:
            break

    return "\n".join(matches) if matches else "(no matches)"


def search_text(pattern, path=".", max_results=200, context=0):
    """在工作区内搜索文本，优先使用 rg。"""
    pattern = str(pattern or "").strip()
    if not pattern:
        return "错误：pattern 不能为空"
    base = _check_path(path)
    if not base.exists():
        return f"错误：路径不存在 {path}"

    max_results = max(1, min(int(max_results), 1000))
    context = max(0, min(int(context), 5))

    if shutil.which("rg"):
        args = [
            "rg",
            "-n",
            "--smart-case",
            "--max-count",
            str(max_results),
        ]
        if context:
            args.extend(["-C", str(context)])
        args.extend([pattern, str(base)])
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            encoding=_ENCODING,
            errors="replace",
            timeout=20,
            cwd=_ROOT,
            env=shell_env(cwd=_ROOT),
        )
        output = (result.stdout or result.stderr or "").strip()
        return output or "(no matches)"

    matches = []
    files = [base] if base.is_file() else [
        item for item in base.rglob("*")
        if item.is_file() and not any(part in _IGNORED_NAMES for part in item.relative_to(_ROOT).parts)
    ]
    needle = pattern.lower()
    for file_path in files:
        try:
            lines = _read_text_file(file_path).splitlines()
        except (OSError, ValueError):
            continue
        for number, line in enumerate(lines, start=1):
            if needle in line.lower():
                matches.append(f"{file_path.relative_to(_ROOT)}:{number}:{line}")
                if len(matches) >= max_results:
                    return "\n".join(matches)
    return "\n".join(matches) if matches else "(no matches)"


def read_many_files(paths, start=1, end=400, max_files=10):
    """一次读取多个文件的行号范围。"""
    if isinstance(paths, str):
        paths = [part.strip() for part in paths.split(",") if part.strip()]
    if not isinstance(paths, list) or not paths:
        return "错误：paths 必须是非空列表或逗号分隔字符串"

    max_files = max(1, min(int(max_files), 20))
    chunks = []
    for path in paths[:max_files]:
        chunks.append(read_file(path, start=start, end=end))
    if len(paths) > max_files:
        chunks.append(f"... 已限制读取前 {max_files} 个文件")
    return "\n\n".join(chunks)


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
    _write_text_file(p, content)
    return f"已写入 {path} ({len(str(content))} 字符)"


def replace_in_file(path, old_text, new_text, expected_replacements=1):
    """在文件中做精确文本替换。默认要求只替换 1 处。"""
    p = _check_path(path)
    if not p.is_file():
        return f"错误：文件不存在 {path}"

    text = _read_text_file(p)
    count = text.count(old_text)
    if count == 0:
        return "错误：未找到 old_text，未修改文件"
    if expected_replacements is not None and count != int(expected_replacements):
        return (
            f"错误：old_text 出现 {count} 次，期望 {expected_replacements} 次，"
            "为避免误替换未修改文件"
        )

    _write_text_file(p, text.replace(old_text, new_text))
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
        text = _read_text_file(p)
        count = text.count(old_text)
        if count == 0:
            return f"错误：第 {i} 个 patch 未找到 old_text，未修改任何文件"
        if expected is not None and count != int(expected):
            return (
                f"错误：第 {i} 个 patch 的 old_text 出现 {count} 次，"
                f"期望 {expected} 次，未修改任何文件"
            )
        prepared.append((p, text, text.replace(old_text, new_text), path, count))

    written = []
    try:
        for p, old_content, new_content, _, _ in prepared:
            _write_text_file(p, new_content)
            written.append((p, old_content))
    except OSError as exc:
        for p, old_content in written:
            try:
                _write_text_file(p, old_content)
            except OSError:
                pass
        return f"错误：写入补丁失败，已尝试回滚: {exc}"

    lines = [f"已应用 {len(prepared)} 个 patch"]
    lines.extend(f"- {path}: 替换 {count} 处" for _, _, _, path, count in prepared)
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


def web_fetch(url, timeout=20, max_chars=20000):
    """抓取网页文本内容。"""
    if not str(url).lower().startswith(("http://", "https://")):
        return "错误：web_fetch 只支持 http:// 或 https:// URL"

    try:
        request = Request(
            str(url),
            headers={
                "User-Agent": "miniAgent/0.1 (+https://github.com/xinjia-ctrl/miniAgent)",
            },
        )
        with urlopen(request, timeout=timeout) as resp:
            content_type = resp.headers.get("content-type", "")
            raw = resp.read(max_chars * 4)

        encoding = "utf-8"
        match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
        if match:
            encoding = match.group(1)

        text = raw.decode(encoding, errors="replace")
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... 已截断到 {max_chars} 字符"
        return f"# {url}\ncontent_type: {content_type}\n\n{text}"
    except HTTPError as e:
        return f"错误：HTTP {e.code} {e.reason}"
    except URLError as e:
        return f"错误：网络请求失败 {e.reason}"
    except Exception as e:
        return f"错误：{type(e).__name__}: {e}"

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
            env=shell_env(cwd=_ROOT),
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return f"exit_code: {result.returncode}\nstdout:\n{stdout.strip()}\nstderr:\n{stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"exit_code: -1\nstdout:\n\nstderr:\n命令超时 ({timeout}s)"
    except Exception as e:
        return f"exit_code: -1\nstdout:\n\nstderr:\n{str(e)}"
