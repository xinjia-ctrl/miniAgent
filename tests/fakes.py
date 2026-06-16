from __future__ import annotations

from pydantic import BaseModel

from pycode_agent.tool_base import BaseTool, ToolContext, ToolResult


class EchoInput(BaseModel):
    text: str


class EchoTool(BaseTool):
    name = "echo"
    description = "测试用回声工具。"
    input_model = EchoInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = EchoInput.model_validate(input_data)
        return ToolResult(display=args.text)
