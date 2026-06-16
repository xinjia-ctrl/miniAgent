from __future__ import annotations

from pycode_agent.memory import MemoryStore
from pycode_agent.tools.todo import TodoItem, TodoWriteInput, TodoWriteTool


def test_memory_store_remember_recall_forget(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    item = store.remember("用户喜欢中文说明", tags=["preference"], importance=5)

    recalled = store.recall("中文", limit=1)
    removed = store.forget(item.id)

    assert recalled[0].id == item.id
    assert removed
    assert store.recall("中文") == []


async def test_todo_write_rejects_multiple_in_progress(tool_context) -> None:
    result = await TodoWriteTool().call(
        TodoWriteInput(
            items=[
                TodoItem(content="a", status="in_progress"),
                TodoItem(content="b", status="in_progress"),
            ]
        ),
        tool_context,
    )

    assert result.is_error
