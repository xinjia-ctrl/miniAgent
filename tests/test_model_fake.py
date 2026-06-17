from __future__ import annotations

from miniagent.config import ModelSettings
from miniagent.messages import TextBlock, assistant_message, tool_result_message
from miniagent.model import (
    AnthropicCompatibleModelClient,
    FakeModelClient,
    ModelRequest,
    OpenAICompatibleModelClient,
    _messages_to_openai,
    create_model_client,
    tool_call_message,
)


async def test_fake_model_returns_scripted_text() -> None:
    client = FakeModelClient(["hello"])
    events = [event async for event in client.stream(ModelRequest(messages=[]))]

    assert events[0].type == "text_delta"
    assert events[-1].type == "assistant_message"
    assert events[-1].data["message"]["content"][0]["text"] == "hello"


async def test_fake_model_returns_scripted_tool_call() -> None:
    message = tool_call_message("read_file", {"file_path": "README.md"}, "读取")
    client = FakeModelClient([message])
    events = [event async for event in client.stream(ModelRequest(messages=[]))]

    content = events[-1].data["message"]["content"]
    assert content[1]["type"] == "tool_use"
    assert content[1]["name"] == "read_file"


async def test_fake_model_accepts_message_item() -> None:
    client = FakeModelClient([assistant_message([TextBlock(text="done")])])
    events = [event async for event in client.stream(ModelRequest(messages=[]))]

    assert events[-1].data["message"]["content"][0]["text"] == "done"


async def test_fake_model_hides_internal_tool_source_marker() -> None:
    client = FakeModelClient()
    request = ModelRequest(
        messages=[
            tool_result_message(
                "tool_1",
                "[source=tool_result trust=untrusted tool=read_file]\nREADME 内容",
            )
        ]
    )

    events = [event async for event in client.stream(request)]

    text = events[-1].data["message"]["content"][0]["text"]
    assert "trust=untrusted" not in text
    assert "README 内容" in text


def test_create_model_client_from_settings() -> None:
    assert isinstance(create_model_client(ModelSettings()), FakeModelClient)
    assert isinstance(
        create_model_client(ModelSettings(provider="openai-compatible", model="gpt-test")),
        OpenAICompatibleModelClient,
    )
    assert isinstance(
        create_model_client(ModelSettings(provider="anthropic-compatible", model="claude-test")),
        AnthropicCompatibleModelClient,
    )


def test_openai_message_conversion_includes_system_prompt() -> None:
    request = ModelRequest(messages=[], system_prompt="system")

    messages = _messages_to_openai(request)

    assert messages == [{"role": "system", "content": "system"}]
