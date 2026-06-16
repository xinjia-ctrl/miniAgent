from __future__ import annotations

from miniagent.tools.glob import GlobInput, GlobTool
from miniagent.tools.grep import GrepInput, GrepTool


async def test_glob_finds_python_files(workspace, tool_context) -> None:
    result = await GlobTool().call(GlobInput(pattern="**/*.py"), tool_context)

    assert "src/app.py" in result.display.replace("\\", "/")


async def test_grep_finds_text(workspace, tool_context) -> None:
    result = await GrepTool().call(GrepInput(pattern="hello"), tool_context)

    assert "README.md:2" in result.display or "src/app.py:1" in result.display
