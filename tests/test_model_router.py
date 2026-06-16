from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from miniagent.config import ModelSettings
from miniagent.messages import TextBlock, ToolUseBlock, assistant_message, tool_result_message
from miniagent.model import (
    AnthropicCompatibleModelClient,
    ModelEvent,
    ModelProviderError,
    ModelRequest,
    ModelRouter,
    ModelUsage,
    _messages_to_anthropic,
    create_model_client,
    normalize_provider_settings,
)
from miniagent.model_router import ANTHROPIC_MESSAGES_URL


class FlakyClient:
    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.attempts += 1
        if self.attempts == 1:
            raise ModelProviderError("fake", "临时失败", retryable=True)
        message = assistant_message([TextBlock(text="ok")])
        yield ModelEvent(type="assistant_message", data={"message": message.model_dump(mode="json")})


class UsageClient:
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        message = assistant_message([TextBlock(text="ok")])
        usage = ModelUsage(
            provider="fake",
            model="fake",
            input_tokens=3,
            output_tokens=2,
            total_tokens=5,
        )
        yield ModelEvent(type="assistant_message", data={"message": message.model_dump(mode="json")})
        yield ModelEvent(type="usage", data=usage.model_dump(mode="json"))


async def test_model_router_retries_retryable_errors() -> None:
    client = FlakyClient()
    router = ModelRouter(
        ModelSettings(provider="fake", max_retries=1),
        factories={"fake": lambda settings: client},
    )

    events = [event async for event in router.stream(ModelRequest(messages=[]))]

    assert client.attempts == 2
    assert events[-1].type == "assistant_message"


async def test_model_router_stores_usage_events() -> None:
    router = ModelRouter(
        ModelSettings(provider="fake"),
        factories={"fake": lambda settings: UsageClient()},
    )

    events = [event async for event in router.stream(ModelRequest(messages=[]))]

    assert events[-1].type == "usage"
    assert router.usage_events[0].total_tokens == 5


def test_anthropic_provider_uses_anthropic_defaults() -> None:
    settings = normalize_provider_settings(
        ModelSettings(provider="anthropic-compatible", model="claude-test")
    )

    assert settings.base_url == ANTHROPIC_MESSAGES_URL
    assert settings.api_key_env == "ANTHROPIC_API_KEY"
    assert isinstance(create_model_client(settings), AnthropicCompatibleModelClient)


def test_anthropic_message_conversion_keeps_tool_blocks() -> None:
    tool_use = ToolUseBlock(id="tool_1", name="read_file", input={"file_path": "README.md"})
    request = ModelRequest(
        messages=[
            assistant_message([TextBlock(text="读取文件"), tool_use]),
            tool_result_message("tool_1", "README 内容"),
        ],
        system_prompt="system",
    )

    messages = _messages_to_anthropic(request)

    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"][1]["type"] == "tool_use"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "tool_result"
    assert messages[1]["content"][0]["tool_use_id"] == "tool_1"


async def test_model_router_does_not_retry_non_retryable_errors() -> None:
    class DeniedClient:
        def __init__(self) -> None:
            self.attempts = 0

        async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
            self.attempts += 1
            raise ModelProviderError("fake", "配置错误", retryable=False)
            yield ModelEvent(type="assistant_message", data={})

    client = DeniedClient()
    router = ModelRouter(
        ModelSettings(provider="fake", max_retries=3),
        factories={"fake": lambda settings: client},
    )

    with pytest.raises(ModelProviderError):
        _ = [event async for event in router.stream(ModelRequest(messages=[]))]

    assert client.attempts == 1
