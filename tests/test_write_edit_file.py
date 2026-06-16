from __future__ import annotations

from pycode_agent.tools.edit_file import EditFileInput, EditFileTool
from pycode_agent.tools.read_file import ReadFileInput, ReadFileTool
from pycode_agent.tools.write_file import WriteFileInput, WriteFileTool


async def test_write_file_requires_read_before_overwrite(workspace, tool_context) -> None:
    result = await WriteFileTool().call(
        WriteFileInput(file_path="README.md", content="new\n"),
        tool_context,
    )

    assert result.is_error or "必须先完整读取" in result.display


async def test_write_file_after_read_updates_file(workspace, tool_context) -> None:
    await ReadFileTool().call(ReadFileInput(file_path="README.md"), tool_context)

    result = await WriteFileTool().call(
        WriteFileInput(file_path="README.md", content="# Demo\nchanged\n"),
        tool_context,
    )

    assert "---" in result.display
    assert (workspace / "README.md").read_text(encoding="utf-8").endswith("changed\n")


async def test_edit_file_replaces_once_after_read(workspace, tool_context) -> None:
    await ReadFileTool().call(ReadFileInput(file_path="README.md"), tool_context)

    result = await EditFileTool().call(
        EditFileInput(file_path="README.md", old_string="hello agent", new_string="hello runtime"),
        tool_context,
    )

    assert not result.is_error
    assert "hello runtime" in (workspace / "README.md").read_text(encoding="utf-8")
