from __future__ import annotations

from miniagent.context import ContextBuilder
from miniagent.config import default_config
from miniagent.engine import QueryEngine
from miniagent.messages import TextBlock, ToolUseBlock, assistant_message, tool_result_message, user_text
from miniagent.model import FakeModelClient
from miniagent.storage import SessionRecord, SessionStorage


def test_context_includes_tools_and_system_prompt(config, registry) -> None:
    request = ContextBuilder().build(
        messages=[user_text("hello")],
        registry=registry,
        config=config,
        state={"todos": [{"content": "写测试", "status": "in_progress"}]},
    )

    assert "权限模式" in request.system_prompt
    assert "写测试" in request.system_prompt
    assert any(tool["name"] == "read_file" for tool in request.tools)


def test_context_includes_last_code_context(config, registry) -> None:
    request = ContextBuilder().build(
        messages=[user_text("hello")],
        registry=registry,
        config=config,
        state={
            "last_code_context": {
                "title": "symbol_search:Service",
                "items": ["src/service.py:3 class Service - 业务服务"],
            }
        },
    )

    assert "相关代码符号" in request.system_prompt
    assert "src/service.py:3 class Service" in request.system_prompt
    assert request.meta["usage"]["code"] > 0


def test_context_trims_old_messages(config, registry) -> None:
    config.context_token_budget = 20
    messages = [user_text("x" * 100), user_text("last")]

    request = ContextBuilder().build(messages=messages, registry=registry, config=config, state={})

    assert request.messages[-1].content[0].text == "last"


def test_context_records_budget_meta_and_compact_summary(config, registry) -> None:
    config.context_token_budget = 24
    state = {}
    messages = [user_text("old " * 200), user_text("middle " * 120), user_text("last")]

    request = ContextBuilder().build(
        messages=messages,
        registry=registry,
        config=config,
        state=state,
    )

    assert request.messages[-1].content[0].text == "last"
    assert request.meta["budget"]["history"] > 0
    assert request.meta["compacted_message_count"] > 0
    assert "compact_summary" in state
    assert "old" in state["compact_summary"]["text"]


def test_context_keeps_tool_use_and_result_atomic(config, registry) -> None:
    config.context_token_budget = 16
    tool_use = ToolUseBlock(id="tool_1", name="read_file", input={"file_path": "README.md"})
    messages = [
        user_text("old " * 200),
        assistant_message([TextBlock(text="读取"), tool_use]),
        tool_result_message("tool_1", "README 内容"),
    ]

    request = ContextBuilder().build(
        messages=messages,
        registry=registry,
        config=config,
        state={},
    )

    selected_text = "\n".join(
        block.type for message in request.messages for block in message.content
    )
    assert len(request.messages) == 2
    assert "tool_use" in selected_text
    assert "tool_result" in selected_text


async def test_engine_saves_compact_summary_to_session(workspace) -> None:
    config = default_config(cwd=workspace, permission_mode="default")
    config.context_token_budget = 24
    storage = SessionStorage(config.resolved_data_dir)
    session = SessionRecord(
        id="sess_compact",
        cwd=str(workspace),
        messages=[user_text("old " * 200), user_text("middle " * 160)],
    )
    engine = QueryEngine(
        config=config,
        storage=storage,
        session=session,
        model_client=FakeModelClient(["完成"]),
    )

    _ = [event async for event in engine.submit("last")]

    saved = storage.load("sess_compact")
    assert saved.state["compact_summary"]["source_message_count"] > 0
    assert saved.state["last_context"]["compacted_message_count"] > 0
