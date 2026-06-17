from __future__ import annotations

from miniagent.config import default_config
from miniagent.engine import QueryEngine
from miniagent.events import DONE, TOOL_RESULT, TOOL_START
from miniagent.model import FakeModelClient, tool_call_message
from miniagent.storage import MESSAGE_APPENDED, TOOL_CALL_APPENDED, TOOL_RESULT_APPENDED


async def test_engine_runs_tool_loop(workspace) -> None:
    model = FakeModelClient(
        [
            tool_call_message("read_file", {"file_path": "README.md"}, "读取"),
            "完成",
        ]
    )
    config = default_config(cwd=workspace, permission_mode="default")
    engine = QueryEngine(model_client=model, config=config)

    events = [event async for event in engine.submit("读取 README.md")]

    assert any(event.type == TOOL_START for event in events)
    assert any(event.type == TOOL_RESULT for event in events)
    assert events[-1].type == DONE
    assert len(model.requests) == 2


async def test_engine_stops_on_final_answer(workspace) -> None:
    model = FakeModelClient(["直接回答"])
    config = default_config(cwd=workspace, permission_mode="default")
    engine = QueryEngine(model_client=model, config=config)

    events = [event async for event in engine.submit("你好")]

    assert events[-1].type == DONE


async def test_engine_writes_audit_log(workspace) -> None:
    model = FakeModelClient([tool_call_message("read_file", {"file_path": "README.md"}), "完成"])
    config = default_config(cwd=workspace, permission_mode="default")
    engine = QueryEngine(model_client=model, config=config)

    _ = [event async for event in engine.submit("读取 README.md")]

    audit_path = config.audit_path
    assert audit_path.exists()
    content = audit_path.read_text(encoding="utf-8")
    assert "request_start" in content
    assert "tool_call" in content
    assert "session_saved" in content


async def test_engine_writes_session_events(workspace) -> None:
    model = FakeModelClient([tool_call_message("read_file", {"file_path": "README.md"}), "完成"])
    config = default_config(cwd=workspace, permission_mode="default")
    engine = QueryEngine(model_client=model, config=config)

    _ = [event async for event in engine.submit("读取 README.md")]
    events = engine.storage.read_events(engine.session_id)

    assert any(event.type == MESSAGE_APPENDED for event in events)
    assert any(event.type == TOOL_CALL_APPENDED for event in events)
    assert any(event.type == TOOL_RESULT_APPENDED for event in events)


async def test_engine_preserves_read_cache_between_tool_turns(workspace) -> None:
    model = FakeModelClient(
        [
            tool_call_message("read_file", {"file_path": "README.md"}),
            tool_call_message(
                "edit_file",
                {
                    "file_path": "README.md",
                    "old_string": "hello agent",
                    "new_string": "hello runtime",
                },
            ),
            "完成",
        ]
    )
    config = default_config(cwd=workspace, permission_mode="accept_edits")
    engine = QueryEngine(model_client=model, config=config)

    events = [event async for event in engine.submit("修改 README.md")]

    assert events[-1].type == DONE
    assert "hello runtime" in (workspace / "README.md").read_text(encoding="utf-8")
