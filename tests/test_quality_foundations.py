from datetime import datetime, timedelta

from miniagent import memory
from miniagent.context import measure_messages
from miniagent.models import AssistantMessage, FakeModelClient, ToolCall
from miniagent.workspace import WorkspaceContext


def test_fake_model_client_returns_deterministic_tool_calls():
    client = FakeModelClient([
        {
            "tool_calls": [
                {"id": "call_1", "name": "read_file", "arguments": '{"path":"README.md"}'},
            ],
        },
        "完成",
    ])

    first = client.chat([{"role": "user", "content": "x"}], tools=[])
    second = client.chat([{"role": "user", "content": "y"}], tools=[])

    assert first.tool_calls == [ToolCall("call_1", "read_file", '{"path":"README.md"}')]
    assert isinstance(second, AssistantMessage)
    assert second.content == "完成"
    assert len(client.calls) == 2


def test_memory_recall_uses_keywords_tags_and_recency(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    old_time = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")

    memory.remember("部署", "生产环境使用蓝色密钥", importance=2, keywords=["deploy", "blue"])
    old_id = memory.remember("杂项", "很久以前的笔记", importance=5, keywords=["old"])
    old_path = memory._path(old_id)
    old_data = old_path.read_text(encoding="utf-8")
    old_path.write_text(old_data.replace(memory._now(), old_time), encoding="utf-8")

    results = memory.recall(query="deploy blue", limit=2)

    assert results[0]["tag"] == "部署"
    assert results[0]["_score"] > results[1]["_score"]


def test_context_measure_reports_compression():
    messages = [
        {"role": "system", "content": "s" * 70000},
        {"role": "user", "content": "u" * 1000},
    ]

    metrics = measure_messages(messages)

    assert metrics["after_chars"] <= metrics["before_chars"]
    assert metrics["message_count_after"] == 2


def test_workspace_refresh_if_changed_detects_document_drift(tmp_path, monkeypatch):
    monkeypatch.setattr("miniagent.workspace.DOC_NAMES", ("README.md",))
    monkeypatch.setattr("miniagent.workspace.INSTRUCTION_FILES", ())
    (tmp_path / "README.md").write_text("v1\n", encoding="utf-8")
    ws = WorkspaceContext(tmp_path)
    ws.repo_root = tmp_path
    ws.refresh()

    unchanged = ws.refresh_if_changed()
    (tmp_path / "README.md").write_text("v2\n", encoding="utf-8")
    changed = ws.refresh_if_changed()

    assert unchanged["changed"] is False
    assert changed["changed"] is True
    assert changed["before"] != changed["after"]
