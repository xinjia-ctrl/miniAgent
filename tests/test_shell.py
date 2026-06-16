from __future__ import annotations

from miniagent.tool_base import ToolContext
from miniagent.tools.shell import ShellInput, ShellTool, is_dangerous_command


def test_dangerous_command_detection() -> None:
    assert is_dangerous_command("git reset --hard")
    assert is_dangerous_command("Remove-Item -Recurse .")
    assert not is_dangerous_command("python --version")


async def test_shell_blocks_dangerous_without_bypass(workspace) -> None:
    context = ToolContext(cwd=str(workspace), session_id="s", permission_mode="default")

    result = await ShellTool().call(ShellInput(command="git reset --hard"), context)

    assert result.is_error
    assert "危险" in result.display


async def test_shell_runs_simple_command_in_bypass(tool_context) -> None:
    result = await ShellTool().call(ShellInput(command="python --version", timeout_seconds=10), tool_context)

    assert "Python" in result.display
