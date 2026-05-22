"""安全辅助：秘密脱敏、shell 环境白名单和文本裁剪。"""

from __future__ import annotations

import os

SECRET_NAME_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")
REDACTED = "<redacted>"
SHELL_ENV_ALLOWLIST = (
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PATHEXT",
    "ProgramData",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "SystemDrive",
    "SystemRoot",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
)


def looks_secret_name(name: str) -> bool:
    upper = str(name).upper()
    return any(marker in upper for marker in SECRET_NAME_MARKERS)


def secret_env_items(env=None):
    env = env or os.environ
    items = []
    for name, value in env.items():
        if value and looks_secret_name(name):
            items.append((name, str(value)))
    return sorted(items, key=lambda item: len(item[1]), reverse=True)


def redact_text(text: str, env=None) -> str:
    result = str(text)
    for _, value in secret_env_items(env=env):
        if len(value) >= 4:
            result = result.replace(value, REDACTED)
    return result


def redact_obj(obj, key=None, env=None):
    if key and looks_secret_name(key):
        return REDACTED
    if isinstance(obj, str):
        return redact_text(obj, env=env)
    if isinstance(obj, list):
        return [redact_obj(item, env=env) for item in obj]
    if isinstance(obj, tuple):
        return [redact_obj(item, env=env) for item in obj]
    if isinstance(obj, dict):
        return {str(item_key): redact_obj(value, key=item_key, env=env) for item_key, value in obj.items()}
    return obj


def shell_env(cwd=None, extra_allowlist=None):
    """构建受限 shell 环境，避免把 API key 等敏感变量传给子进程。"""
    allowed = set(SHELL_ENV_ALLOWLIST)
    if extra_allowlist:
        allowed.update(str(name) for name in extra_allowlist)
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    if cwd is not None:
        env["PWD"] = str(cwd)
    return env


def clip_text(text, limit):
    text = str(text)
    limit = int(limit)
    if len(text) <= limit:
        return text
    if limit <= 20:
        return text[:limit]
    return text[:limit] + f"\n... 已截断 {len(text) - limit} 字符"
