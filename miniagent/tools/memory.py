from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from miniagent.memory import MemoryScope, MemoryStore, default_memory_path
from miniagent.tool_base import BaseTool, ToolContext, ToolResult


class RememberInput(BaseModel):
    content: str
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(default=1, ge=1, le=10)
    scope: MemoryScope = "project"


class ForgetMemoryInput(BaseModel):
    memory_id: str


class RecallMemoryInput(BaseModel):
    query: str = ""
    tags: list[str] = Field(default_factory=list)
    scope: Literal["user", "project", "session"] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class RememberTool(BaseTool):
    name = "remember"
    description = "保存一条跨会话持久记忆。"
    input_model = RememberInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = RememberInput.model_validate(input_data)
        item = _store(context).remember(
            args.content,
            args.tags,
            args.importance,
            scope=args.scope,
            project=_project(context) if args.scope == "project" else None,
            session_id=context.session_id if args.scope == "session" else None,
            source="tool:remember",
        )
        return ToolResult(display=f"已记住：{item.id}", structured_content={"memory": item.model_dump()})


class ForgetMemoryTool(BaseTool):
    name = "forget_memory"
    description = "删除一条持久记忆。"
    input_model = ForgetMemoryInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = ForgetMemoryInput.model_validate(input_data)
        removed = _store(context).forget(args.memory_id)
        return ToolResult(display="已删除" if removed else "未找到记忆", is_error=not removed)


class RecallMemoryTool(BaseTool):
    name = "recall_memory"
    description = "按关键词召回持久记忆。"
    input_model = RecallMemoryInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = RecallMemoryInput.model_validate(input_data)
        hits = _store(context).recall_hits(
            args.query,
            args.limit,
            tags=args.tags,
            scope=args.scope,
            project=_project(context),
            session_id=context.session_id,
        )
        memories = [hit.item.model_dump(mode="json") for hit in hits]
        recall = [
            {
                "id": hit.item.id,
                "scope": hit.item.scope,
                "score": hit.score,
                "matched_keywords": hit.matched_keywords,
                "matched_tags": hit.matched_tags,
                "reason": hit.reason,
            }
            for hit in hits
        ]
        context.state["memories"] = memories
        context.state["memory_injections"] = recall
        context.state["last_memory_recall"] = recall
        lines = [
            (
                f"- {hit.item.id} [{hit.item.scope}] score={hit.score:.2f}: "
                f"{hit.item.content}\n  reason: {hit.reason}"
            )
            for hit in hits
        ]
        return ToolResult(
            display="\n".join(lines) if lines else "没有召回到相关记忆。",
            structured_content={"memories": memories, "recall": recall},
        )


def _store(context: ToolContext) -> MemoryStore:
    path = context.state.get("memory_path")
    if not path:
        path = default_memory_path(data_dir=context.data_dir, cwd=context.cwd)
    return MemoryStore(path)


def _project(context: ToolContext) -> str:
    return str(Path(context.cwd).resolve())
