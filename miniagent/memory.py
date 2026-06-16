from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, Field

from miniagent.utils.ids import new_id


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    content: str
    tags: list[str] = Field(default_factory=list)
    importance: int = 1
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def remember(self, content: str, tags: list[str] | None = None, importance: int = 1) -> MemoryItem:
        item = MemoryItem(content=content, tags=tags or [], importance=importance)
        items = self._load()
        items.append(item)
        self._save(items)
        return item

    def forget(self, memory_id: str) -> bool:
        items = self._load()
        kept = [item for item in items if item.id != memory_id]
        self._save(kept)
        return len(kept) != len(items)

    def recall(self, query: str = "", limit: int = 5) -> list[MemoryItem]:
        items = self._load()
        words = {word.lower() for word in query.split() if word.strip()}

        def score(item: MemoryItem) -> tuple[int, float]:
            haystack = " ".join([item.content, *item.tags]).lower()
            matched = sum(1 for word in words if word in haystack)
            return (matched + item.importance, item.updated_at)

        return sorted(items, key=score, reverse=True)[:limit]

    def _load(self) -> list[MemoryItem]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [MemoryItem.model_validate(item) for item in raw]

    def _save(self, items: list[MemoryItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
