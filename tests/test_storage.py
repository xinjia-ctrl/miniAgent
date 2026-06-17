from __future__ import annotations

from miniagent.messages import user_text
from miniagent.storage import (
    MESSAGE_APPENDED,
    PERMISSION_DECISION_APPENDED,
    SESSION_STARTED,
    TOOL_CALL_APPENDED,
    TOOL_RESULT_APPENDED,
    SessionRecord,
    SessionStorage,
)


def test_session_storage_save_load_latest(tmp_path) -> None:
    storage = SessionStorage(tmp_path / ".data")
    record = SessionRecord(id="sess_1", cwd=str(tmp_path), messages=[user_text("hi")])

    path = storage.save(record)
    loaded = storage.load("sess_1")
    latest = storage.load_latest()

    assert path.exists()
    assert loaded.messages[0].content[0].text == "hi"
    assert latest is not None
    assert latest.id == "sess_1"


def test_session_storage_writes_event_log_and_index(tmp_path) -> None:
    storage = SessionStorage(tmp_path / ".data")
    record = SessionRecord(
        id="sess_events",
        cwd=str(tmp_path),
        messages=[user_text("hi")],
        tool_calls=[{"id": "tool_1", "name": "read_file", "input": {"file_path": "README.md"}}],
        tool_results=[{"display": "ok", "is_error": False}],
        permission_decisions=[{"allowed": True, "action": "allow", "reason": "test"}],
        state={"last_context": {"selected_message_count": 1}},
    )

    storage.save(record)
    events = storage.read_events("sess_events")
    sessions = storage.list_sessions()

    assert storage.event_path("sess_events").exists()
    assert events[0].type == SESSION_STARTED
    assert any(event.type == MESSAGE_APPENDED for event in events)
    assert any(event.type == TOOL_CALL_APPENDED for event in events)
    assert any(event.type == TOOL_RESULT_APPENDED for event in events)
    assert any(event.type == PERMISSION_DECISION_APPENDED for event in events)
    assert sessions[0].id == "sess_events"
    assert sessions[0].message_count == 1


def test_session_storage_rebuilds_session_from_events(tmp_path) -> None:
    storage = SessionStorage(tmp_path / ".data")
    record = SessionRecord(
        id="sess_rebuild",
        cwd=str(tmp_path),
        messages=[user_text("first")],
        state={"compact_summary": {"text": "old"}},
    )
    storage.save(record)
    record.messages.append(user_text("second"))
    record.state["last_context"] = {"selected_message_count": 2}
    storage.save(record)

    events = storage.read_events("sess_rebuild")
    rebuilt = storage.load_from_events("sess_rebuild")
    exported = storage.export("sess_rebuild")

    message_events = [event for event in events if event.type == MESSAGE_APPENDED]
    assert len(message_events) == 2
    assert rebuilt.messages[0].content[0].text == "first"
    assert rebuilt.messages[1].content[0].text == "second"
    assert rebuilt.state["last_context"]["selected_message_count"] == 2
    assert exported["snapshot"]["id"] == "sess_rebuild"
    assert exported["rebuilt"]["messages"][1]["content"][0]["text"] == "second"
