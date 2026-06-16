from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Any, Protocol

from pydantic import BaseModel, Field

from pycode_agent.messages import (
    ContentBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    assistant_message,
    assistant_text,
    message_text,
)
from pycode_agent.config import ModelSettings
from pycode_agent.utils.ids import new_id
from pycode_agent.utils.text import clip_text


class ModelRequest(BaseModel):
    messages: list[Message]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class ModelEvent(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class ModelClient(Protocol):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        raise NotImplementedError


def create_model_client(settings: ModelSettings) -> ModelClient:
    if settings.provider == "fake":
        return FakeModelClient()
    if settings.provider == "openai-compatible":
        return OpenAICompatibleModelClient(settings)
    raise ValueError(f"未知模型 provider：{settings.provider}")


class FakeModelClient:
    """确定性模型客户端。

    传入 script 时，每次模型请求消费一个脚本响应。未传入 script 时使用很小的
    启发式回复，方便 CLI 在没有真实模型的情况下也能演示完整流程。
    """

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
            return assistant_text("已收到工具结果：\n" + clip_text(message_text(last), 1200))

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
    blocks = []
    if text:
        blocks.append(TextBlock(text=text))
    blocks.append(ToolUseBlock(id=new_id("tool"), name=name, input=input_data))
    return assistant_message(blocks)


class OpenAICompatibleModelClient:
    """最小 OpenAI-compatible chat completions 适配器。

    这个适配器刻意保持小：测试仍依赖 FakeModelClient，真实模型只作为运行时可选项。
    它支持普通文本回复，也支持 OpenAI tool_calls 转换为内部 ToolUseBlock。
    """

    def __init__(self, settings: ModelSettings):
        self.settings = settings

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        message = await asyncio.to_thread(self._complete, request)
        for block in message.content:
            if isinstance(block, TextBlock):
                yield ModelEvent(type="text_delta", data={"text": block.text})
        yield ModelEvent(type="assistant_message", data={"message": message.model_dump(mode="json")})

    def _complete(self, request: ModelRequest) -> Message:
        api_key = os.environ.get(self.settings.api_key_env)
        if not api_key:
            raise RuntimeError(f"缺少环境变量：{self.settings.api_key_env}")

        payload = {
            "model": self.settings.model,
            "messages": _messages_to_openai(request),
            "tools": _tools_to_openai(request.tools),
            "stream": False,
        }
        if not payload["tools"]:
            payload.pop("tools")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            self.settings.base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.settings.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"模型请求失败：HTTP {exc.code} {clip_text(detail, 1000)}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"模型请求失败：{exc.reason}") from exc

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
        return assistant_message(blocks or [TextBlock(text="")])


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
