from __future__ import annotations

from pathlib import Path


def clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n...[已截断 {omitted} 字符]"


def is_probably_binary_bytes(data: bytes) -> bool:
    if not data:
        return False
    return b"\x00" in data or b"\xef\xbf\xbd" in data


def is_probably_binary_file(path: Path, sample_size: int = 4096) -> bool:
    return is_probably_binary_bytes(path.read_bytes()[:sample_size])


def read_text(path: Path) -> str:
    if is_probably_binary_file(path):
        raise ValueError("拒绝读取疑似二进制文件")
    return path.read_text(encoding="utf-8")


def format_with_line_numbers(content: str, *, start_line: int = 1) -> str:
    lines = content.splitlines()
    return "\n".join(f"{index:>4} | {line}" for index, line in enumerate(lines, start=start_line))
