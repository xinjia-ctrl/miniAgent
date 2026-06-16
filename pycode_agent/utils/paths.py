from __future__ import annotations

import os
from pathlib import Path


SENSITIVE_FILENAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_dsa"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def resolve_workspace_path(
    cwd: str | Path,
    user_path: str | Path,
    *,
    allow_missing: bool = False,
    disallow_sensitive: bool = True,
) -> Path:
    root = Path(cwd).resolve(strict=False)
    raw = Path(user_path)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve(strict=False)

    try:
        common = os.path.commonpath([str(root), str(resolved)])
    except ValueError as exc:
        raise ValueError(f"路径不在工作区内：{user_path}") from exc
    if common != str(root):
        raise ValueError(f"路径不在工作区内：{user_path}")

    if ".git" in resolved.parts:
        raise ValueError("禁止访问 .git 目录")
    if disallow_sensitive and is_sensitive_path(resolved):
        raise ValueError(f"禁止访问敏感文件：{resolved.name}")
    if not allow_missing and not resolved.exists():
        raise FileNotFoundError(f"文件不存在：{user_path}")
    return resolved


def is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    return name in SENSITIVE_FILENAMES or path.suffix.lower() in SENSITIVE_SUFFIXES


def relative_to_workspace(cwd: str | Path, path: str | Path) -> str:
    root = Path(cwd).resolve(strict=False)
    return str(Path(path).resolve(strict=False).relative_to(root))
