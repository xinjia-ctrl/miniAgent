from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from miniagent.messages import Message


class SessionRecord(BaseModel):
    id: str
    cwd: str
    messages: list[Message] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    permission_decisions: list[dict[str, Any]] = Field(default_factory=list)
    todos: list[dict[str, Any]] = Field(default_factory=list)
    file_reads: dict[str, dict[str, Any]] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class SessionStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.latest_path = self.root / "latest"

    def save(self, record: SessionRecord) -> Path:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        record.updated_at = time.time()
        path = self.session_path(record.id)
        path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        self.latest_path.write_text(record.id, encoding="utf-8")
        return path

    def load(self, session_id: str) -> SessionRecord:
        path = self.session_path(session_id)
        return SessionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def load_latest(self) -> SessionRecord | None:
        if not self.latest_path.exists():
            return None
        session_id = self.latest_path.read_text(encoding="utf-8").strip()
        if not session_id:
            return None
        return self.load(session_id)

    def session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"
