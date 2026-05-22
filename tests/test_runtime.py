import json
from pathlib import Path

from miniagent.models import AssistantMessage, ToolCall
from miniagent.run_store import RunStore
from miniagent.runtime import AgentRuntime
from miniagent import session as session_module


class FakeBackend:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.model = "fake"
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(("chat", list(messages), tools))
        return self.outputs.pop(0)

    def chat_stream(self, messages, tools=None, on_text=None):
        self.calls.append(("chat_stream", list(messages), tools))
        msg = self.outputs.pop(0)
        if on_text and msg.content:
            on_text(msg.content)
            msg.streamed = True
        return msg


def _make_runtime(tmp_path, backend=None, func_map=None, parallel_safe_tools=None):
    return AgentRuntime(
        backend=backend or FakeBackend([]),
        tools=[],
        func_map=func_map or {},
        refresh_system_message=lambda messages: None,
        check_permission=lambda name, args, session_id=None: (True, "allowed"),
        log_tool_call=lambda session_id, name, args: None,
        log_tool_result=lambda session_id, name, result: None,
        print_tool_result=lambda result: None,
        run_store=RunStore(tmp_path / "runs"),
        parallel_safe_tools=parallel_safe_tools or set(),
    )


def test_exec_direct_writes_run_artifacts(tmp_path):
    runtime = _make_runtime(
        tmp_path,
        func_map={"echo": lambda text: f"ok:{text}"},
    )

    result = runtime.exec_direct("echo", {"text": "hello"})

    assert result == "ok:hello"
    run_dirs = list((tmp_path / "runs").glob("run_*"))
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "trace.jsonl").exists()
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "success"
    assert report["tool"] == "echo"


def test_handle_tool_calls_records_tool_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSION_DIR", tmp_path / "sessions")
    session_id = session_module.create_session()

    backend = FakeBackend([
        AssistantMessage(content="完成"),
    ])
    runtime = _make_runtime(
        tmp_path,
        backend=backend,
        func_map={"read_file": lambda path: f"content:{path}"},
    )
    messages = [{"role": "system", "content": "sys"}]
    first = AssistantMessage(
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                name="read_file",
                arguments=json.dumps({"path": "README.md"}),
            )
        ],
    )

    final, extra, streamed = runtime.handle_tool_calls(first, messages, session_id)

    assert final == "完成"
    assert extra == {}
    assert streamed is True
    assert any(msg.get("role") == "tool" and msg.get("content") == "content:README.md" for msg in messages)
    saved = session_module.load_messages(session_id)
    assert [item["role"] for item in saved] == ["assistant", "tool"]


def test_parallel_safe_tool_calls_keep_result_order(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSION_DIR", tmp_path / "sessions")
    session_id = session_module.create_session()

    backend = FakeBackend([
        AssistantMessage(content="完成"),
    ])
    runtime = _make_runtime(
        tmp_path,
        backend=backend,
        func_map={
            "first": lambda: "one",
            "second": lambda: "two",
        },
        parallel_safe_tools={"first", "second"},
    )
    messages = [{"role": "system", "content": "sys"}]
    first = AssistantMessage(
        tool_calls=[
            ToolCall(id="call_1", name="first", arguments="{}"),
            ToolCall(id="call_2", name="second", arguments="{}"),
        ],
    )

    runtime.handle_tool_calls(first, messages, session_id)

    tool_messages = [msg for msg in messages if msg.get("role") == "tool"]
    assert [msg["tool_call_id"] for msg in tool_messages] == ["call_1", "call_2"]
    assert [msg["content"] for msg in tool_messages] == ["one", "two"]
