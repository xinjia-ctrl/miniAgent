from __future__ import annotations

from miniagent.memory import MemoryStore


def test_memory_store_supports_three_scopes(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    user = store.remember("用户偏好中文", scope="user")
    project = store.remember("项目使用 pytest", scope="project", project="repo")
    session = store.remember("当前会话正在修复记忆", scope="session", session_id="sess")

    assert user in store.list_memories(scope="user")
    assert project in store.list_memories(scope="project", project="repo")
    assert session in store.list_memories(scope="session", session_id="sess")


def test_memory_recall_explains_keyword_tag_and_decay(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    item = store.remember("提交前运行 pytest", tags=["test"], importance=5)

    hit = store.recall_hits("pytest", tags=["test"], limit=1)[0]

    assert hit.item.id == item.id
    assert hit.score > 0
    assert hit.reason
    assert hit.matched_keywords == ["pytest"]
    assert hit.matched_tags == ["test"]
