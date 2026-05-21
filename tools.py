# tools.py - 阶段一
# 工具函数：AI 通过调用这些函数来操作你的电脑

import locale
import subprocess
from pathlib import Path

# 工作区根目录：所有文件操作都被限定在这个目录下
ROOT = Path.cwd().resolve()
# 使用系统编码（Windows 上通常是 gbk）
_ENCODING = locale.getpreferredencoding()

def _check_path(path):
    """安全校验：确保路径不逃逸出工作区

    这是 miniAgent 最重要的安全机制之一。
    如果 AI 试图读 /etc/passwd 或 ../secret.txt，这里会拦截。
    """
    p = Path(str(path))
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    # 检查路径是否在以 ROOT 开头
    if str(ROOT) not in str(p) and str(p) != str(ROOT):
        raise ValueError(f"路径逃逸: {path}")
    return p

def read_file(path, start=1, end=200):
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
    items = []
    for item in sorted(p.iterdir()):
        kind = "[D]" if item.is_dir() else "[F]"
        items.append(f"{kind} {item.name}")
    return "\n".join(items) if items else "(空目录)"

def run_shell(command, timeout=20):
    """执行 shell 命令（危险的！）"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding=_ENCODING,
            errors="replace",
            timeout=timeout,
            cwd=ROOT,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return f"exit_code: {result.returncode}\nstdout:\n{stdout.strip()}\nstderr:\n{stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"exit_code: -1\nstdout:\n\nstderr:\n命令超时 ({timeout}s)"
    except Exception as e:
        return f"exit_code: -1\nstdout:\n\nstderr:\n{str(e)}"
