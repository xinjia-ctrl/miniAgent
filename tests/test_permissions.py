from __future__ import annotations

from miniagent.permissions import PermissionManager
from miniagent.tool_base import ToolContext
from miniagent.tools.read_file import ReadFileInput, ReadFileTool
from miniagent.tools.shell import ShellInput, ShellTool
from miniagent.tools.write_file import WriteFileInput, WriteFileTool


async def test_default_allows_read_tool(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="default")

    decision = await manager.decide(ReadFileTool(), ReadFileInput(file_path="README.md"), context)

    assert decision.allowed


async def test_default_denies_write_in_non_interactive(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="default")

    decision = await manager.decide(WriteFileTool(), WriteFileInput(file_path="a.txt", content="x"), context)

    assert not decision.allowed


async def test_accept_edits_allows_write(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="accept_edits")

    decision = await manager.decide(WriteFileTool(), WriteFileInput(file_path="a.txt", content="x"), context)

    assert decision.allowed


async def test_plan_denies_shell(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="plan")

    decision = await manager.decide(ShellTool(), ShellInput(command="python --version"), context)

    assert not decision.allowed


async def test_bypass_allows_shell(workspace) -> None:
    manager = PermissionManager(non_interactive=True)
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="bypass")

    decision = await manager.decide(ShellTool(), ShellInput(command="python --version"), context)

    assert decision.allowed
