from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from miniagent.memory import MemoryStore
from miniagent.tool_base import BaseTool, ToolContext, ToolResult


class RememberInput(BaseModel):
    content: str
    tags: list[str] = Field(default_factory=list)
    importance: int = Field(default=1, ge=1, le=10)


class ForgetMemoryInput(BaseModel):
    memory_id: str


class RecallMemoryInput(BaseModel):
    query: str = ""
    limit: int = Field(default=5, ge=1, le=20)


class RememberTool(BaseTool):
    name = "remember"
    description = "保存一条跨会话持久记忆。"
    input_model = RememberInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = RememberInput.model_validate(input_data)
        item = _store(context).remember(args.content, args.tags, args.importance)
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
        items = _store(context).recall(args.query, args.limit)
        context.state["memories"] = [item.model_dump(mode="json") for item in items]
        lines = [f"- {item.id}: {item.content}" for item in items]
        return ToolResult(display="\n".join(lines), structured_content={"memories": context.state["memories"]})


def _store(context: ToolContext) -> MemoryStore:
    path = context.state.get("memory_path")
    if not path:
        path = str(Path(context.cwd) / ".miniagent" / "memory.json")
    return MemoryStore(path)
