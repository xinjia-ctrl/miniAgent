from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudget:
    total: int
    system: int
    project: int
    memory: int
    history: int
    tool: int
    protected: int

    @classmethod
    def for_total(cls, total: int) -> ContextBudget:
        total = max(1, total)
        system = max(1, int(total * 0.20))
        project = max(1, int(total * 0.10))
        memory = max(1, int(total * 0.15))
        tool = max(1, int(total * 0.25))
        protected = max(1, int(total * 0.15))
        history = max(1, total - system - project - memory - tool - protected)
        return cls(
            total=total,
            system=system,
            project=project,
            memory=memory,
            history=history,
            tool=tool,
            protected=protected,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "system": self.system,
            "project": self.project,
            "memory": self.memory,
            "history": self.history,
            "tool": self.tool,
            "protected": self.protected,
        }
