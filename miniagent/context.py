from __future__ import annotations

from dataclasses import dataclass
import json
import platform
from typing import Any, Literal

from miniagent.config import AgentConfig
from miniagent.context_budget import ContextBudget
from miniagent.messages import Message, ToolResultBlock, ToolUseBlock, message_text
from miniagent.model import ModelRequest
from miniagent.prompts import build_system_prompt
from miniagent.tool_base import ToolRegistry
from miniagent.utils.git import git_status_summary
from miniagent.utils.tokens import estimate_tokens


@dataclass(frozen=True)
class MessageUnit:
    messages: list[Message]
    start_index: int
    token_count: int
    category: Literal["history", "tool"]

    @property
    def end_index(self) -> int:
        return self.start_index + len(self.messages)


class ContextBuilder:
    def build(
        self,
        *,
        messages: list[Message],
        registry: ToolRegistry,
        config: AgentConfig,
        state: dict[str, Any] | None = None,
    ) -> ModelRequest:
        if state is None:
            state = {}
        git_status = git_status_summary(config.cwd)
        compact_summary = state.get("compact_summary", {})
        platform_name = platform.platform()
        memory_context = self._format_memory_context(state)
        code_context = self._format_code_context(state)
        system_prompt = build_system_prompt(
            cwd=config.cwd,
            platform=platform_name,
            permission_mode=config.permission_mode,
            git_status=git_status,
            todos=self._format_todos(state.get("todos", [])),
            memories=memory_context,
            code_context=code_context,
        )
        tools = registry.tool_schemas()
        budget = ContextBudget.for_total(config.context_token_budget)
        selected, selection_meta = self._select_messages(
            messages=messages,
            budget=budget,
            system_prompt=system_prompt,
            tools=tools,
            state=state,
        )
        if state.get("compact_summary") != compact_summary:
            memory_context = self._format_memory_context(state)
            code_context = self._format_code_context(state)
            system_prompt = build_system_prompt(
                cwd=config.cwd,
                platform=platform_name,
                permission_mode=config.permission_mode,
                git_status=git_status,
                todos=self._format_todos(state.get("todos", [])),
                memories=memory_context,
                code_context=code_context,
            )
        prompt_tokens = estimate_tokens(system_prompt)
        tools_tokens = estimate_tokens(json.dumps(tools, ensure_ascii=False))
        project_tokens = estimate_tokens(
            "\n".join([config.cwd, platform_name, config.permission_mode, git_status])
        )
        memory_tokens = estimate_tokens(memory_context)
        code_tokens = estimate_tokens(code_context)
        memory_ids = self._memory_ids(state.get("memories", []))
        context_meta = {
            "cwd": config.cwd,
            "permission_mode": config.permission_mode,
            "budget": budget.as_dict(),
            "usage": {
                "system": max(0, prompt_tokens - project_tokens - memory_tokens - code_tokens),
                "project": project_tokens,
                "memory": memory_tokens,
                "code": code_tokens,
                "tools": tools_tokens,
                "history": selection_meta["history_tokens"],
                "tool": selection_meta["tool_tokens"],
                "protected": selection_meta["protected_tokens"],
            },
            "total_message_count": len(messages),
            "selected_message_count": len(selected),
            "compacted_message_count": selection_meta["compacted_message_count"],
            "compact_summary": state.get("compact_summary"),
            "included_memory_ids": memory_ids,
            "memory_recall": state.get("last_memory_recall", []),
        }
        state["last_context"] = context_meta
        return ModelRequest(
            messages=selected,
            tools=tools,
            system_prompt=system_prompt,
            meta=context_meta,
        )

    @staticmethod
    def _trim_messages(messages: list[Message], budget: int, system_prompt: str) -> list[Message]:
        state: dict[str, Any] = {}
        selected, _ = ContextBuilder._select_messages(
            messages=messages,
            budget=ContextBudget.for_total(budget),
            system_prompt=system_prompt,
            tools=[],
            state=state,
        )
        return selected

    @staticmethod
    def _select_messages(
        *,
        messages: list[Message],
        budget: ContextBudget,
        system_prompt: str,
        tools: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> tuple[list[Message], dict[str, int]]:
        units = ContextBuilder._message_units(messages)
        if not units:
            return [], {
                "history_tokens": 0,
                "tool_tokens": 0,
                "protected_tokens": 0,
                "compacted_message_count": 0,
            }

        fixed_tokens = estimate_tokens(system_prompt) + estimate_tokens(
            json.dumps(tools, ensure_ascii=False)
        )
        available_for_messages = max(budget.protected, budget.total - fixed_tokens)
        history_remaining = min(budget.history, available_for_messages)
        tool_remaining = min(budget.tool, available_for_messages)
        protected_remaining = min(budget.protected, available_for_messages)
        selected_indexes: set[int] = set()
        selected_units: list[tuple[MessageUnit, str]] = []
        protected_open = True

        for unit in reversed(units):
            selected_as: str | None = None
            if protected_open and (not selected_units or unit.token_count <= protected_remaining):
                selected_as = "protected"
                protected_remaining = max(0, protected_remaining - unit.token_count)
            else:
                protected_open = False
                if unit.category == "tool" and unit.token_count <= tool_remaining:
                    selected_as = "tool"
                    tool_remaining -= unit.token_count
                elif unit.category == "history" and unit.token_count <= history_remaining:
                    selected_as = "history"
                    history_remaining -= unit.token_count

            if selected_as:
                selected_units.append((unit, selected_as))
                selected_indexes.update(range(unit.start_index, unit.end_index))

        omitted_units = [unit for unit in units if unit.start_index not in selected_indexes]
        if omitted_units:
            state["compact_summary"] = ContextBuilder._build_compact_summary(
                omitted_units,
                previous=state.get("compact_summary"),
            )

        selected_messages = [
            message for index, message in enumerate(messages) if index in selected_indexes
        ]
        return selected_messages, {
            "history_tokens": sum(
                unit.token_count for unit, selected_as in selected_units if selected_as == "history"
            ),
            "tool_tokens": sum(
                unit.token_count for unit, selected_as in selected_units if selected_as == "tool"
            ),
            "protected_tokens": sum(
                unit.token_count for unit, selected_as in selected_units if selected_as == "protected"
            ),
            "compacted_message_count": sum(len(unit.messages) for unit in omitted_units),
        }

    @staticmethod
    def _message_units(messages: list[Message]) -> list[MessageUnit]:
        units: list[MessageUnit] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            tool_use_ids = {
                block.id for block in message.content if isinstance(block, ToolUseBlock)
            }
            grouped = [message]
            category: Literal["history", "tool"] = "tool" if tool_use_ids else "history"
            next_index = index + 1
            while tool_use_ids and next_index < len(messages):
                candidate = messages[next_index]
                result_ids = {
                    block.tool_use_id
                    for block in candidate.content
                    if isinstance(block, ToolResultBlock)
                }
                if not result_ids or not result_ids.issubset(tool_use_ids):
                    break
                grouped.append(candidate)
                next_index += 1
            token_count = sum(estimate_tokens(message_text(item)) for item in grouped)
            units.append(
                MessageUnit(
                    messages=grouped,
                    start_index=index,
                    token_count=token_count,
                    category=category,
                )
            )
            index = next_index
        return units

    @staticmethod
    def _build_compact_summary(
        omitted_units: list[MessageUnit],
        *,
        previous: Any = None,
    ) -> dict[str, Any]:
        source_message_ids = [
            message.id for unit in omitted_units for message in unit.messages
        ]
        if isinstance(previous, dict) and previous.get("source_message_ids") == source_message_ids:
            return previous

        previous_text = ""
        if isinstance(previous, dict):
            previous_text = str(previous.get("text") or "")
        elif isinstance(previous, str):
            previous_text = previous

        lines = []
        if previous_text:
            lines.append(previous_text)
        for unit in omitted_units:
            for message in unit.messages:
                text = message_text(message).replace("\n", " ")
                lines.append(f"- {message.role}: {text[:240]}")
        compact_text = "\n".join(lines)
        if len(compact_text) > 2400:
            compact_text = compact_text[-2400:]
        return {
            "text": compact_text,
            "source_message_count": sum(len(unit.messages) for unit in omitted_units),
            "source_message_ids": source_message_ids,
            "strategy": "deterministic-message-compact",
        }

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
                memory_id = getattr(item, "id", None)
                scope = getattr(item, "scope", None)
                prefix = f"[{memory_id}]" if memory_id else ""
                if scope:
                    prefix = f"{prefix}[{scope}]"
                content = str(item.content)
                lines.append(f"- {prefix} {content}" if prefix else f"- {content}")
            elif isinstance(item, dict):
                memory_id = item.get("id")
                scope = item.get("scope")
                prefix = f"[{memory_id}]" if memory_id else ""
                if scope:
                    prefix = f"{prefix}[{scope}]"
                content = str(item.get("content", ""))
                lines.append(f"- {prefix} {content}" if prefix else f"- {content}")
        return "\n".join(lines)

    @staticmethod
    def _memory_ids(memories: list[Any]) -> list[str]:
        ids: list[str] = []
        for item in memories:
            memory_id = getattr(item, "id", None)
            if isinstance(item, dict):
                memory_id = item.get("id")
            if memory_id:
                ids.append(str(memory_id))
        return ids

    @staticmethod
    def _format_memory_context(state: dict[str, Any]) -> str:
        parts = []
        memories = ContextBuilder._format_memories(state.get("memories", []))
        if memories:
            parts.append(memories)
        summary = state.get("compact_summary")
        if isinstance(summary, dict) and summary.get("text"):
            parts.append("历史摘要：\n" + str(summary["text"]))
        elif isinstance(summary, str) and summary:
            parts.append("历史摘要：\n" + summary)
        return "\n\n".join(parts)

    @staticmethod
    def _format_code_context(state: dict[str, Any]) -> str:
        value = state.get("last_code_context")
        if not isinstance(value, dict):
            return ""
        title = str(value.get("title") or "last_code_context")
        raw_items = value.get("items", [])
        if not isinstance(raw_items, list):
            return ""
        lines = [f"{title}:"]
        for item in raw_items[:30]:
            lines.append(f"- {item}")
        return "\n".join(lines)
