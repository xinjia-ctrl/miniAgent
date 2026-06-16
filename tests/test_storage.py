from __future__ import annotations

from pycode_agent.messages import user_text
from pycode_agent.storage import SessionRecord, SessionStorage


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
