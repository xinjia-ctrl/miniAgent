from __future__ import annotations

from miniagent.messages import TextBlock, assistant_message
from miniagent.config import ModelSettings
from miniagent.model import (
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


def test_create_model_client_from_settings() -> None:
    assert isinstance(create_model_client(ModelSettings()), FakeModelClient)
    assert isinstance(
        create_model_client(ModelSettings(provider="openai-compatible", model="gpt-test")),
        OpenAICompatibleModelClient,
    )


def test_openai_message_conversion_includes_system_prompt() -> None:
    request = ModelRequest(messages=[], system_prompt="system")

    messages = _messages_to_openai(request)

    assert messages == [{"role": "system", "content": "system"}]
