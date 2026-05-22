import json

import miniagent.cli as cli
from miniagent.models import AssistantMessage, FakeModelClient, ToolCall


def test_delegate_rejects_non_readonly_tool(monkeypatch):
    backend = FakeModelClient([
        AssistantMessage(tool_calls=[
            ToolCall("call_1", "write_file", json.dumps({"path": "x.txt", "content": "bad"})),
        ]),
        AssistantMessage(content="完成"),
    ])
    monkeypatch.setattr(cli, "backend", backend)
    monkeypatch.setattr(cli, "_build_system_content", lambda: "system")

    result = cli._delegate_task("try write", max_steps=2)

    assert result == "完成"
    call_messages = backend.calls[-1]["messages"]
    assert any(
        msg.get("role") == "tool" and "拒绝非只读工具" in msg.get("content", "")
        for msg in call_messages
    )


def test_delegate_can_use_readonly_tool(monkeypatch):
    backend = FakeModelClient([
        AssistantMessage(tool_calls=[
            ToolCall("call_1", "read_file", json.dumps({"path": "README.md"})),
        ]),
        AssistantMessage(content="调查完成"),
    ])
    monkeypatch.setattr(cli, "backend", backend)
    monkeypatch.setattr(cli, "_build_system_content", lambda: "system")
    monkeypatch.setitem(cli.FUNC_MAP, "read_file", lambda path: f"read:{path}")

    result = cli._delegate_task("read readme", max_steps=2)

    assert result == "调查完成"
