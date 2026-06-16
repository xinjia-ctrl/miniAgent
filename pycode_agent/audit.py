from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pycode_agent.utils.jsonl import append_jsonl


SENSITIVE_KEYS = {"api_key", "token", "password", "secret"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if key.lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class AuditLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def log(self, event_type: str, data: dict[str, Any]) -> None:
        append_jsonl(
            self.path,
            {"type": event_type, "created_at": time.time(), "data": redact(data)},
        )
