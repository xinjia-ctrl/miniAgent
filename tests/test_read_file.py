from __future__ import annotations

import pytest

from pycode_agent.tools.read_file import ReadFileInput, ReadFileTool


async def test_read_file_returns_line_numbers(workspace, tool_context) -> None:
    result = await ReadFileTool().call(ReadFileInput(file_path="README.md"), tool_context)

    assert "1 | # Demo" in result.display
    assert "README.md" in next(iter(tool_context.file_reads))


async def test_read_file_rejects_path_escape(workspace, tool_context, tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("no", encoding="utf-8")

    with pytest.raises(ValueError):
        await ReadFileTool().call(ReadFileInput(file_path=str(outside)), tool_context)


async def test_read_file_rejects_binary(workspace, tool_context) -> None:
    (workspace / "bin.dat").write_bytes(b"a\x00b")

    with pytest.raises(ValueError):
        await ReadFileTool().call(ReadFileInput(file_path="bin.dat"), tool_context)
