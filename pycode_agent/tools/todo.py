from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pycode_agent.tool_base import BaseTool, EmptyInput, ToolContext, ToolResult


class TodoItem(BaseModel):
    content: str
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoWriteInput(BaseModel):
    items: list[TodoItem] = Field(default_factory=list)


class TodoReadTool(BaseTool):
    name = "todo_read"
    description = "读取当前任务列表。"
    input_model = EmptyInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        todos = context.state.get("todos", [])
        lines = [f"- [{item.get('status', 'pending')}] {item.get('content', '')}" for item in todos]
        return ToolResult(display="\n".join(lines), structured_content={"todos": todos})


class TodoWriteTool(BaseTool):
    name = "todo_write"
    description = "更新当前任务列表，最多允许一个 in_progress。"
    input_model = TodoWriteInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = TodoWriteInput.model_validate(input_data)
        in_progress = [item for item in args.items if item.status == "in_progress"]
        if len(in_progress) > 1:
            return ToolResult(display="最多只能有一个 in_progress 任务", is_error=True)
        todos = [item.model_dump(mode="json") for item in args.items]
        context.state["todos"] = todos
        return ToolResult(display="Todo 已更新", structured_content={"todos": todos})
