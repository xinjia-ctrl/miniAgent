from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterable
from typing import Any

from miniagent.config import ModelSettings
from miniagent.messages import (
    ContentBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    assistant_message,
    assistant_text,
    message_text,
)
from miniagent.model_base import (
    ModelEvent,
    ModelProviderError,
    ModelRequest,
    ModelUsage,
    ProviderResponse,
)
from miniagent.utils.ids import new_id
from miniagent.utils.text import clip_text


class FakeModelClient:
    """确定性模型客户端，用于 harness、测试和本地演示。"""

    def __init__(self, script: Iterable[str | Message | list[ModelEvent] | ModelEvent] | None = None):
        self._script = list(script or [])
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.requests.append(request)
        if self._script:
            item = self._script.pop(0)
            async for event in self._events_from_script_item(item):
                yield event
            return

        message = self._default_response(request)
        for block in message.content:
            if isinstance(block, TextBlock):
                yield ModelEvent(type="text_delta", data={"text": block.text})
        yield ModelEvent(type="assistant_message", data={"message": message.model_dump(mode="json")})

    async def _events_from_script_item(
        self, item: str | Message | list[ModelEvent] | ModelEvent
    ) -> AsyncIterator[ModelEvent]:
        if isinstance(item, str):
            message = assistant_text(item)
            yield ModelEvent(type="text_delta", data={"text": item})
            yield ModelEvent(type="assistant_message", data={"message": message.model_dump(mode="json")})
            return
        if isinstance(item, Message):
            for block in item.content:
                if isinstance(block, TextBlock):
                    yield ModelEvent(type="text_delta", data={"text": block.text})
            yield ModelEvent(type="assistant_message", data={"message": item.model_dump(mode="json")})
            return
        if isinstance(item, ModelEvent):
            yield item
            return
        for event in item:
            yield event

    def _default_response(self, request: ModelRequest) -> Message:
        last = request.messages[-1] if request.messages else None
        if last and any(isinstance(block, ToolResultBlock) for block in last.content):
            tool_text = _strip_internal_source_markers(message_text(last))
            return assistant_text("已收到工具结果：\n" + clip_text(tool_text, 1200))

        prompt = message_text(last) if last else ""
        if "README.md" in prompt and not self._has_recent_tool_result(request):
            return assistant_message(
                [
                    TextBlock(text="我先读取 README.md。"),
                    ToolUseBlock(
                        id=new_id("tool"),
                        name="read_file",
                        input={"file_path": "README.md"},
                    ),
                ]
            )
        return assistant_text(f"FakeModel 已收到：{prompt}")

    @staticmethod
    def _has_recent_tool_result(request: ModelRequest) -> bool:
        return any(
            isinstance(block, ToolResultBlock)
            for message in request.messages[-2:]
            for block in message.content
        )


def tool_call_message(name: str, input_data: dict[str, Any], text: str = "") -> Message:
    blocks: list[ContentBlock] = []
    if text:
        blocks.append(TextBlock(text=text))
    blocks.append(ToolUseBlock(id=new_id("tool"), name=name, input=input_data))
    return assistant_message(blocks)


def _strip_internal_source_markers(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if "[source=tool_result " not in line
    )


class OpenAICompatibleModelClient:
    """OpenAI-compatible chat completions 适配器。"""

    provider = "openai-compatible"

    def __init__(self, settings: ModelSettings):
        self.settings = settings

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        response = await asyncio.to_thread(self._complete, request)
        async for event in _response_events(response):
            yield event

    def _complete(self, request: ModelRequest) -> ProviderResponse:
        api_key = os.environ.get(self.settings.api_key_env)
        if not api_key:
            raise ModelProviderError(
                self.provider,
                f"缺少环境变量：{self.settings.api_key_env}",
                retryable=False,
            )

        payload = {
            "model": self.settings.model,
            "messages": _messages_to_openai(request),
            "tools": _tools_to_openai(request.tools),
            "stream": False,
        }
        if not payload["tools"]:
            payload.pop("tools")
        data = _post_json(
            provider=self.provider,
            url=self.settings.base_url,
            payload=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout_seconds=self.settings.timeout_seconds,
        )

        choice = data["choices"][0]["message"]
        blocks: list[ContentBlock] = []
        if choice.get("content"):
            blocks.append(TextBlock(text=choice["content"]))
        for tool_call in choice.get("tool_calls") or []:
            function = tool_call.get("function", {})
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {"raw_arguments": raw_arguments}
            blocks.append(
                ToolUseBlock(
                    id=tool_call.get("id") or new_id("tool"),
                    name=function.get("name", ""),
                    input=arguments,
                )
            )
        usage = _openai_usage(data.get("usage"), self.settings)
        return ProviderResponse(message=assistant_message(blocks or [TextBlock(text="")]), usage=usage)


class AnthropicCompatibleModelClient:
    """Anthropic-style messages 适配器。"""

    provider = "anthropic-compatible"

    def __init__(self, settings: ModelSettings):
        self.settings = settings

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        response = await asyncio.to_thread(self._complete, request)
        async for event in _response_events(response):
            yield event

    def _complete(self, request: ModelRequest) -> ProviderResponse:
        api_key = os.environ.get(self.settings.api_key_env)
        if not api_key:
            raise ModelProviderError(
                self.provider,
                f"缺少环境变量：{self.settings.api_key_env}",
                retryable=False,
            )

        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": _messages_to_anthropic(request),
            "tools": _tools_to_anthropic(request.tools),
            "max_tokens": self.settings.max_output_tokens,
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if not payload["tools"]:
            payload.pop("tools")
        data = _post_json(
            provider=self.provider,
            url=self.settings.base_url,
            payload=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": self.settings.anthropic_version,
                "Content-Type": "application/json",
            },
            timeout_seconds=self.settings.timeout_seconds,
        )
        blocks: list[ContentBlock] = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                blocks.append(TextBlock(text=block.get("text", "")))
            elif block.get("type") == "tool_use":
                blocks.append(
                    ToolUseBlock(
                        id=block.get("id") or new_id("tool"),
                        name=block.get("name", ""),
                        input=block.get("input") or {},
                    )
                )
        usage = _anthropic_usage(data.get("usage"), self.settings)
        return ProviderResponse(message=assistant_message(blocks or [TextBlock(text="")]), usage=usage)


async def _response_events(response: ProviderResponse) -> AsyncIterator[ModelEvent]:
    for block in response.message.content:
        if isinstance(block, TextBlock):
            yield ModelEvent(type="text_delta", data={"text": block.text})
    yield ModelEvent(
        type="assistant_message",
        data={"message": response.message.model_dump(mode="json")},
    )
    if response.usage:
        yield ModelEvent(type="usage", data=response.usage.model_dump(mode="json"))


def _post_json(
    *,
    provider: str,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ModelProviderError(
            provider,
            f"模型请求失败：HTTP {exc.code} {clip_text(detail, 1000)}",
            retryable=exc.code == 429 or 500 <= exc.code < 600,
        ) from exc
    except urllib.error.URLError as exc:
        raise ModelProviderError(provider, f"模型请求失败：{exc.reason}", retryable=True) from exc


def _messages_to_openai(request: ModelRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    for message in request.messages:
        tool_results = [block for block in message.content if isinstance(block, ToolResultBlock)]
        if tool_results:
            for block in tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.tool_use_id,
                        "content": block.content,
                    }
                )
            continue

        text = "\n".join(block.text for block in message.content if isinstance(block, TextBlock))
        tool_uses = [block for block in message.content if isinstance(block, ToolUseBlock)]
        item: dict[str, Any] = {"role": message.role, "content": text or None}
        if tool_uses:
            item["tool_calls"] = [
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    },
                }
                for block in tool_uses
            ]
        messages.append(item)
    return messages


def _tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object"}),
                },
            }
        )
    return converted


def _messages_to_anthropic(request: ModelRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in request.messages:
        content: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                content.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
            elif isinstance(block, ToolResultBlock):
                content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    }
                )
        role = "assistant" if message.role == "assistant" else "user"
        messages.append({"role": role, "content": content or [{"type": "text", "text": ""}]})
    return messages


def _tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        converted.append(
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema", {"type": "object"}),
            }
        )
    return converted


def _openai_usage(raw: dict[str, Any] | None, settings: ModelSettings) -> ModelUsage | None:
    if not raw:
        return None
    return ModelUsage(
        provider="openai-compatible",
        model=settings.model,
        input_tokens=raw.get("prompt_tokens"),
        output_tokens=raw.get("completion_tokens"),
        total_tokens=raw.get("total_tokens"),
    )


def _anthropic_usage(raw: dict[str, Any] | None, settings: ModelSettings) -> ModelUsage | None:
    if not raw:
        return None
    input_tokens = raw.get("input_tokens")
    output_tokens = raw.get("output_tokens")
    total_tokens = None
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    return ModelUsage(
        provider="anthropic-compatible",
        model=settings.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
