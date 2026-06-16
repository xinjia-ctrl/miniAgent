from __future__ import annotations

from pycode_agent.tool_base import ToolRegistry
from pycode_agent.tools.edit_file import EditFileTool
from pycode_agent.tools.glob import GlobTool
from pycode_agent.tools.grep import GrepTool
from pycode_agent.tools.memory import ForgetMemoryTool, RecallMemoryTool, RememberTool
from pycode_agent.tools.plan import PlanUpdateTool
from pycode_agent.tools.read_file import ReadFileTool
from pycode_agent.tools.shell import ShellTool
from pycode_agent.tools.todo import TodoReadTool, TodoWriteTool
from pycode_agent.tools.write_file import WriteFileTool


def register_builtin_tools(registry: ToolRegistry) -> None:
    for tool in [
        ReadFileTool(),
        GlobTool(),
        GrepTool(),
        WriteFileTool(),
        EditFileTool(),
        ShellTool(),
        TodoReadTool(),
        TodoWriteTool(),
        RememberTool(),
        ForgetMemoryTool(),
        RecallMemoryTool(),
        PlanUpdateTool(),
    ]:
        registry.register(tool)


def builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry
