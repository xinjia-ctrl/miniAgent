from __future__ import annotations

from pathlib import Path

from miniagent.config import default_config
from miniagent.context import ContextBuilder
from miniagent.memory import MemoryStore, default_memory_path
from miniagent.messages import user_text
from miniagent.tool_base import ToolContext
from miniagent.tools import builtin_registry
from miniagent.tools.memory import RecallMemoryInput, RecallMemoryTool


async def test_recall_memory_records_explainable_context_injection(workspace) -> None:
    data_dir = workspace / ".miniagent"
    project_key = str(Path(workspace).resolve())
    store = MemoryStore(default_memory_path(data_dir=data_dir, cwd=workspace))
    item = store.remember(
        "本项目提交前运行 pytest",
        tags=["test"],
        importance=5,
        scope="project",
        project=project_key,
    )
    tool_context = ToolContext(
        cwd=str(workspace),
        session_id="sess_memory",
        permission_mode="bypass",
        data_dir=str(data_dir),
    )

    result = await RecallMemoryTool().call(RecallMemoryInput(query="pytest"), tool_context)

    assert not result.is_error
    assert tool_context.state["memories"][0]["id"] == item.id
    assert tool_context.state["memory_injections"][0]["id"] == item.id
    assert "score" in tool_context.state["memory_injections"][0]
    assert "reason" in tool_context.state["memory_injections"][0]

    request = ContextBuilder().build(
        messages=[user_text("测试命令是什么？")],
        registry=builtin_registry(),
        config=default_config(cwd=workspace, permission_mode="bypass"),
        state=tool_context.state,
    )

    assert item.id in request.system_prompt
    assert request.meta["included_memory_ids"] == [item.id]
