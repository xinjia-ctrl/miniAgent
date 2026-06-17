from __future__ import annotations

from pathlib import Path


SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SENSITIVE_PARTS = {".git", ".ssh", ".gnupg"}


def is_sensitive_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        bool(parts & SENSITIVE_PARTS)
        or name in SENSITIVE_FILENAMES
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    )


def sensitive_path_reason(path: Path) -> str | None:
    if is_sensitive_path(path):
        return f"禁止访问敏感路径：{path.name}"
    return None
