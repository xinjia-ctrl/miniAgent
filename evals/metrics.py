from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalMetrics:
    completed: bool
    tool_calls: int
    permission_denials: int
    errors: int
    expected_file_modified: bool = False
    dangerous_behavior_blocked: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "completed": self.completed,
            "tool_calls": self.tool_calls,
            "permission_denials": self.permission_denials,
            "errors": self.errors,
            "expected_file_modified": self.expected_file_modified,
            "dangerous_behavior_blocked": self.dangerous_behavior_blocked,
        }
