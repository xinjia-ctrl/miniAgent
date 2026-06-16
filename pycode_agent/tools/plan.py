from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pycode_agent.tool_base import BaseTool, ToolContext, ToolResult


class PlanStep(BaseModel):
    step: str
    status: Literal["pending", "in_progress", "completed"] = "pending"


class PlanUpdateInput(BaseModel):
    steps: list[PlanStep]


class PlanUpdateTool(BaseTool):
    name = "plan_update"
    description = "记录阶段计划，不直接修改文件。"
    input_model = PlanUpdateInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = PlanUpdateInput.model_validate(input_data)
        plan = [item.model_dump(mode="json") for item in args.steps]
        context.state["plan"] = plan
        lines = [f"- [{item['status']}] {item['step']}" for item in plan]
        return ToolResult(display="\n".join(lines), structured_content={"plan": plan})
