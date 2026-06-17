from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from miniagent.security.secrets import redact_sensitive
from miniagent.utils.jsonl import append_jsonl


def redact(value: Any) -> Any:
    return redact_sensitive(value)


class AuditLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def log(self, event_type: str, data: dict[str, Any]) -> None:
        append_jsonl(
            self.path,
            {"type": event_type, "created_at": time.time(), "data": redact(data)},
        )
