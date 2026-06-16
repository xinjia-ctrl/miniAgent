from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel

from miniagent.tool_base import BaseTool, ToolContext


class PermissionMode(str, Enum):
    default = "default"
    accept_edits = "accept_edits"
    plan = "plan"
    bypass = "bypass"


class PermissionDecision(BaseModel):
    allowed: bool
    action: str
    reason: str


ConfirmCallback = Callable[[str, str], bool | Awaitable[bool]]


class PermissionManager:
    def __init__(self, confirmer: ConfirmCallback | None = None, non_interactive: bool = True):
        self.confirmer = confirmer
        self.non_interactive = non_interactive

    async def decide(self, tool: BaseTool, input_data: object, context: ToolContext) -> PermissionDecision:
        mode = PermissionMode(context.permission_mode)
        if mode is PermissionMode.bypass:
            return PermissionDecision(allowed=True, action="allow", reason="bypass 模式允许执行")

        read_only = tool.is_read_only(input_data)  # type: ignore[arg-type]
        planning_tool = tool.name in {"plan_update", "todo_read", "todo_write"}
        memory_tool = tool.name in {"remember", "forget_memory", "recall_memory"}

        if mode is PermissionMode.plan:
            if read_only or planning_tool or tool.name == "recall_memory":
                return PermissionDecision(allowed=True, action="allow", reason="plan 模式允许只读和计划工具")
            return PermissionDecision(allowed=False, action="deny", reason="plan 模式禁止修改文件或执行命令")

        if read_only or planning_tool or memory_tool:
            return PermissionDecision(allowed=True, action="allow", reason="只读或状态工具允许执行")

        if mode is PermissionMode.accept_edits and tool.name in {"write_file", "edit_file"}:
            return PermissionDecision(allowed=True, action="allow", reason="accept_edits 模式允许文件编辑")

        return await self._ask_or_deny(tool.name, context)

    async def _ask_or_deny(self, tool_name: str, context: ToolContext) -> PermissionDecision:
        if self.non_interactive or self.confirmer is None:
            return PermissionDecision(allowed=False, action="deny", reason="非交互模式下需要确认的工具被拒绝")
        value = self.confirmer(tool_name, context.cwd)
        if inspect.isawaitable(value):
            value = await value
        if value:
            return PermissionDecision(allowed=True, action="allow", reason="用户确认允许执行")
        return PermissionDecision(allowed=False, action="deny", reason="用户拒绝执行")
