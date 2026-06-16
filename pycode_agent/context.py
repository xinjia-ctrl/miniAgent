from __future__ import annotations

import platform
from typing import Any

from pycode_agent.config import AgentConfig
from pycode_agent.messages import Message, message_text
from pycode_agent.model import ModelRequest
from pycode_agent.prompts import build_system_prompt
from pycode_agent.tool_base import ToolRegistry
from pycode_agent.utils.git import git_status_summary
from pycode_agent.utils.tokens import estimate_tokens


class ContextBuilder:
    def build(
        self,
        *,
        messages: list[Message],
        registry: ToolRegistry,
        config: AgentConfig,
        state: dict[str, Any] | None = None,
    ) -> ModelRequest:
        state = state or {}
        system_prompt = build_system_prompt(
            cwd=config.cwd,
            platform=platform.platform(),
            permission_mode=config.permission_mode,
            git_status=git_status_summary(config.cwd),
            todos=self._format_todos(state.get("todos", [])),
            memories=self._format_memories(state.get("memories", [])),
        )
        selected = self._trim_messages(messages, config.context_token_budget, system_prompt)
        return ModelRequest(
            messages=selected,
            tools=registry.tool_schemas(),
            system_prompt=system_prompt,
            meta={"cwd": config.cwd, "permission_mode": config.permission_mode},
        )

    @staticmethod
    def _trim_messages(messages: list[Message], budget: int, system_prompt: str) -> list[Message]:
        total = estimate_tokens(system_prompt)
        selected: list[Message] = []
        for message in reversed(messages):
            cost = estimate_tokens(message_text(message))
            if selected and total + cost > budget:
                break
            selected.append(message)
            total += cost
        selected.reverse()
        return selected

    @staticmethod
    def _format_todos(todos: list[dict[str, Any]]) -> str:
        lines = []
        for item in todos:
            lines.append(f"- [{item.get('status', 'pending')}] {item.get('content', '')}")
        return "\n".join(lines)

    @staticmethod
    def _format_memories(memories: list[Any]) -> str:
        lines = []
        for item in memories:
            if hasattr(item, "content"):
                lines.append(f"- {item.content}")
            elif isinstance(item, dict):
                lines.append(f"- {item.get('content', '')}")
        return "\n".join(lines)
