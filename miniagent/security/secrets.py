from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEY_FRAGMENTS = {"api_key", "apikey", "token", "password", "secret", "credential"}


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if is_sensitive_key(key) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return redact_secret_text(value)
    return value


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact_secret_text(text: str) -> str:
    patterns = [
        (r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?([^\s'\",]+)", r"\1=***"),
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "***"),
        (r"\bAKIA[0-9A-Z]{16}\b", "***"),
    ]
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted
