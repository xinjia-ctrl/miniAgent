from __future__ import annotations

import time

from miniagent.memory import MemoryStore, build_session_memory_candidates
from miniagent.messages import user_text
from miniagent.tools.todo import TodoItem, TodoWriteInput, TodoWriteTool


def test_memory_store_remember_recall_forget(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    item = store.remember("用户喜欢中文说明", tags=["preference"], importance=5)

    recalled = store.recall("中文", limit=1)
    removed = store.forget(item.id)

    assert recalled[0].id == item.id
    assert removed
    assert store.recall("中文") == []


def test_memory_store_scopes_update_and_explain_recall(tmp_path) -> None:
    now = time.time()
    store = MemoryStore(tmp_path / "memory.json")
    user = store.remember(
        "默认使用中文解释",
        tags=["preference"],
        importance=4,
        scope="user",
    )
    project = store.remember(
        "本项目测试命令是 pytest",
        tags=["test"],
        importance=3,
        scope="project",
        project="repo-a",
    )
    other_project = store.remember(
        "其他项目使用 npm test",
        tags=["test"],
        importance=10,
        scope="project",
        project="repo-b",
    )
    store.update(project.id, content="本项目测试命令是 python -m pytest", tags=["test", "pytest"])

    hits = store.recall_hits("pytest", tags=["test"], project="repo-a", now=now)

    assert [hit.item.id for hit in hits] == [project.id]
    assert hits[0].matched_keywords == ["pytest"]
    assert hits[0].matched_tags == ["test"]
    assert "score=" in hits[0].reason
    assert other_project.id not in [item.id for item in store.list_memories(project="repo-a")]
    assert user.id in [item.id for item in store.list_memories(project="repo-a")]


def test_memory_store_time_decay_prefers_fresh_memory(tmp_path) -> None:
    now = time.time()
    store = MemoryStore(tmp_path / "memory.json")
    old = store.remember("pytest 旧规则", tags=["test"], importance=3)
    fresh = store.remember("pytest 新规则", tags=["test"], importance=3)
    items = store._load()
    for item in items:
        if item.id == old.id:
            item.updated_at = now - 90 * 86400
        if item.id == fresh.id:
            item.updated_at = now
    store._save(items)

    hits = store.recall_hits("pytest", now=now)

    assert hits[0].item.id == fresh.id
    assert hits[0].recency_score > hits[1].recency_score


def test_build_session_memory_candidates_requires_memory_signal() -> None:
    candidates = build_session_memory_candidates(
        [user_text("请记住：我偏好先运行 pytest 再提交")],
        session_id="sess_memory",
    )

    assert candidates
    assert candidates[0].source == "session:sess_memory"
    assert "pytest" in candidates[0].content


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
