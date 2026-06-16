from __future__ import annotations

from miniagent.tool_base import ToolRegistry
from miniagent.tools.edit_file import EditFileTool
from miniagent.tools.glob import GlobTool
from miniagent.tools.grep import GrepTool
from miniagent.tools.memory import ForgetMemoryTool, RecallMemoryTool, RememberTool
from miniagent.tools.plan import PlanUpdateTool
from miniagent.tools.read_file import ReadFileTool
from miniagent.tools.shell import ShellTool
from miniagent.tools.todo import TodoReadTool, TodoWriteTool
from miniagent.tools.write_file import WriteFileTool


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
