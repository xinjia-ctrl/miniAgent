from __future__ import annotations

import re

from pydantic import BaseModel, Field

from pycode_agent.tool_base import BaseTool, ToolContext, ToolResult
from pycode_agent.utils.subprocess import run_subprocess


class ShellInput(BaseModel):
    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class ShellTool(BaseTool):
    name = "shell"
    description = "在工作区执行 shell 命令，带超时、输出截断和危险命令拦截。"
    input_model = ShellInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = ShellInput.model_validate(input_data)
        if is_dangerous_command(args.command) and context.permission_mode != "bypass":
            return ToolResult(display="危险 shell 命令被拦截", is_error=True)
        result = await run_subprocess(
            args.command,
            cwd=context.cwd,
            timeout_seconds=args.timeout_seconds,
            max_output_chars=context.max_result_chars,
        )
        display = (
            f"exit_code: {result.exit_code}\n"
            f"timed_out: {result.timed_out}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        return ToolResult(display=display, is_error=result.exit_code != 0)


def is_dangerous_command(command: str) -> bool:
    normalized = re.sub(r"\s+", " ", command.strip().lower())
    patterns = [
        r"\bremove-item\b",
        r"\bdel\b",
        r"\brmdir\b",
        r"\brd\b",
        r"\bformat\b",
        r"\bdiskpart\b",
        r"\bgit reset --hard\b",
        r"\bgit clean\b",
    ]
    return any(re.search(pattern, normalized) for pattern in patterns)
