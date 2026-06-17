from __future__ import annotations

from miniagent.permissions import PermissionManager
from miniagent.tool_base import ToolContext, ToolRegistry
from miniagent.tool_runner import ToolCall, ToolRunner, partition_tool_calls
from fakes import EchoTool


async def test_tool_runner_executes_registered_tool(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    runner = ToolRunner(registry, PermissionManager(non_interactive=True))
    context = ToolContext(cwd=str(tmp_path), session_id="s", permission_mode="default")

    results = await runner.run_calls([ToolCall(id="tool_1", name="echo", input={"text": "hi"})], context)

    assert results[0].result.display == "hi"
    assert not results[0].result.is_error
    assert results[0].result.structured_content["source"]["trust"] == "untrusted"


async def test_tool_runner_turns_unknown_tool_into_error(tmp_path) -> None:
    runner = ToolRunner(ToolRegistry(), PermissionManager(non_interactive=True))
    context = ToolContext(cwd=str(tmp_path), session_id="s", permission_mode="default")

    results = await runner.run_calls([ToolCall(id="tool_1", name="missing", input={})], context)

    assert results[0].result.is_error
    assert "未知工具" in results[0].result.display


def test_partition_tool_calls_marks_read_only_concurrent() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    concurrent, serial = partition_tool_calls(
        [ToolCall(id="tool_1", name="echo", input={"text": "x"})],
        registry,
    )

    assert len(concurrent) == 1
    assert serial == []
