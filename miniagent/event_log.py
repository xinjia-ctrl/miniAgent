from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from miniagent.utils.ids import new_id
from miniagent.utils.jsonl import append_jsonl, read_jsonl


class StorageEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    session_id: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class EventLog:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def append(self, *, session_id: str, event_type: str, data: dict[str, Any]) -> StorageEvent:
        event = StorageEvent(session_id=session_id, type=event_type, data=data)
        append_jsonl(self.path_for(session_id), event.model_dump(mode="json"))
        return event

    def read(self, session_id: str) -> list[StorageEvent]:
        return [StorageEvent.model_validate(row) for row in read_jsonl(self.path_for(session_id))]

    def path_for(self, session_id: str) -> Path:
        return self.root / f"{session_id}.jsonl"
