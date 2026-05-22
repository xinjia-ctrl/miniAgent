"""AI 模型客户端：统一接口，可插拔

新增后端只需继承 BaseClient 并实现 chat() 和 name。
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass


# ===================================================================
#  统一数据类型
# ===================================================================

@dataclass
class ToolCall:
    """标准化的工具调用"""
    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class AssistantMessage:
    """标准化的助手响应"""
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None
    streamed: bool = False


# ===================================================================
#  抽象基类
# ===================================================================

class BaseClient(ABC):
    """AI 客户端基类，所有后端继承此接口"""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AssistantMessage:
        """发送聊天请求，返回统一格式的 AssistantMessage"""
        ...

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_text=None,
    ) -> AssistantMessage:
        """流式聊天。默认降级为非流式，子类可覆盖。"""
        msg = self.chat(messages, tools=tools)
        if on_text and msg.content:
            on_text(msg.content)
            msg.streamed = True
        return msg

    @property
    @abstractmethod
    def name(self) -> str:
        """客户端标识名，如 openai / anthropic / ollama"""
        ...

    @property
    def model(self) -> str:
        return self.config.get("model", "unknown")


# ===================================================================
#  1. OpenAI / 兼容客户端（DeepSeek、OpenAI 等）
# ===================================================================

class OpenAIClient(BaseClient):
    """OpenAI 及兼容 API（DeepSeek、OpenAI、任何兼容端点）"""

    def __init__(self, config: dict):
        super().__init__(config)
        from openai import OpenAI
        self.client = OpenAI(
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
        )

    @property
    def name(self) -> str:
        return "openai"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AssistantMessage:
        kwargs = dict(model=self.model, messages=messages, stream=False)
        if tools:
            kwargs["tools"] = tools

        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in msg.tool_calls
            ]

        return AssistantMessage(
            content=msg.content,
            tool_calls=tool_calls,
            reasoning_content=_get_reasoning_content(msg),
        )

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_text=None,
    ) -> AssistantMessage:
        return _stream_openai_chat(
            self.client,
            self.model,
            messages,
            tools=tools,
            on_text=on_text,
        )


# ===================================================================
#  2. Anthropic Claude 客户端
# ===================================================================

class AnthropicClient(BaseClient):
    """Anthropic Claude API，自动处理消息格式转换"""

    def __init__(self, config: dict):
        super().__init__(config)
        from anthropic import Anthropic
        self.client = Anthropic(api_key=config.get("api_key"))

    @property
    def name(self) -> str:
        return "anthropic"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AssistantMessage:
        system, msgs = self._split_system(messages)
        api_kwargs = dict(
            model=self.model,
            messages=msgs,
            max_tokens=self.config.get("max_tokens", 4096),
        )
        if system:
            api_kwargs["system"] = system
        if tools:
            api_kwargs["tools"] = _to_anthropic_tools(tools)

        resp = self.client.messages.create(**api_kwargs)

        # 解析 content blocks → text + tool_calls
        text_parts = []
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=json.dumps(block.input),
                    )
                )

        return AssistantMessage(
            content="".join(text_parts) or None,
            tool_calls=tool_calls or None,
        )

    # ---- 消息格式转换 ----

    @staticmethod
    def _split_system(messages):
        """从消息列表中分离 system prompt"""
        system = None
        msgs = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                msgs.append(AnthropicClient._to_anthropic_msg(m))
        return system, msgs

    @staticmethod
    def _to_anthropic_msg(msg):
        """OpenAI 格式消息 → Anthropic 格式"""
        role = msg["role"]

        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return {"role": "user", "content": content}
            blocks = []
            for block in content:
                if block.get("type") == "tool_result":
                    blocks.append({
                        "type": "tool_result",
                        "tool_use_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    })
                else:
                    blocks.append(block)
            return {"role": "user", "content": blocks}

        if role == "assistant":
            content = msg.get("content") or ""
            tc = msg.get("tool_calls")
            if not tc:
                return {"role": "assistant", "content": content}
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
            for t in tc:
                fn = t.get("function", {})
                blocks.append({
                    "type": "tool_use",
                    "id": t["id"],
                    "name": fn.get("name", ""),
                    "input": json.loads(fn.get("arguments", "{}")),
                })
            return {"role": "assistant", "content": blocks}

        if role == "tool":
            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg["tool_call_id"],
                    "content": msg.get("content", ""),
                }],
            }

        return {"role": role, "content": msg.get("content", "")}


# ===================================================================
#  3. Ollama 本地模型客户端
# ===================================================================

class OllamaClient(BaseClient):
    """Ollama 本地模型（通过 OpenAI 兼容端点 /v1 调用）"""

    def __init__(self, config: dict):
        super().__init__(config)
        from openai import OpenAI
        base = config.get("base_url", "http://localhost:11434").rstrip("/")
        self.client = OpenAI(
            api_key="ollama",  # Ollama 不需要 key，但 SDK 要求必填
            base_url=f"{base}/v1",
        )

    @property
    def name(self) -> str:
        return "ollama"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AssistantMessage:
        kwargs = dict(model=self.model, messages=messages, stream=False)
        if tools:
            kwargs["tools"] = tools

        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in msg.tool_calls
            ]

        return AssistantMessage(
            content=msg.content,
            tool_calls=tool_calls,
            reasoning_content=_get_reasoning_content(msg),
        )

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_text=None,
    ) -> AssistantMessage:
        return _stream_openai_chat(
            self.client,
            self.model,
            messages,
            tools=tools,
            on_text=on_text,
        )


def _stream_openai_chat(client, model, messages, tools=None, on_text=None) -> AssistantMessage:
    """聚合 OpenAI-compatible 流式响应，兼容文本、tool_calls 和 reasoning_content"""
    kwargs = dict(model=model, messages=messages, stream=True)
    if tools:
        kwargs["tools"] = tools

    content_parts = []
    reasoning_parts = []
    tool_calls = {}
    streamed = False

    for chunk in client.chat.completions.create(**kwargs):
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        content = getattr(delta, "content", None)
        if content:
            content_parts.append(content)
            streamed = True
            if on_text:
                on_text(content)

        reasoning = _get_reasoning_content(delta)
        if reasoning:
            reasoning_parts.append(reasoning)

        for tc in getattr(delta, "tool_calls", None) or []:
            index = getattr(tc, "index", None)
            if index is None:
                index = len(tool_calls)
            item = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})

            tc_id = getattr(tc, "id", None)
            if tc_id:
                item["id"] = tc_id

            fn = getattr(tc, "function", None)
            if fn:
                name = getattr(fn, "name", None)
                arguments = getattr(fn, "arguments", None)
                if name:
                    item["name"] = name
                if arguments:
                    item["arguments"] += arguments

    parsed_tool_calls = []
    for _, item in sorted(tool_calls.items()):
        if item["name"]:
            parsed_tool_calls.append(
                ToolCall(
                    id=item["id"],
                    name=item["name"],
                    arguments=item["arguments"] or "{}",
                )
            )

    return AssistantMessage(
        content="".join(content_parts) or None,
        tool_calls=parsed_tool_calls or None,
        reasoning_content="".join(reasoning_parts) or None,
        streamed=streamed,
    )


def _get_reasoning_content(message) -> str | None:
    """兼容 DeepSeek 等 OpenAI-compatible 接口返回的 reasoning_content"""
    value = getattr(message, "reasoning_content", None)
    if value:
        return value

    model_extra = getattr(message, "model_extra", None) or {}
    value = model_extra.get("reasoning_content")
    return value or None


# ===================================================================
#  工具函数：OpenAI tools → Anthropic tools
# ===================================================================

def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """转换 tools 格式供 Anthropic 使用"""
    result = []
    for t in tools:
        fn = t.get("function", {})
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {}),
        })
    return result


# ===================================================================
#  工厂：按配置创建客户端
# ===================================================================

CLIENTS: dict[str, type[BaseClient]] = {
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
    "ollama": OllamaClient,
}


def create_backend(config: dict) -> BaseClient:
    """工厂函数，根据 config.provider 创建对应的客户端实例"""
    provider = config.get("provider", "openai")
    cls = CLIENTS.get(provider)
    if not cls:
        raise ValueError(
            f"未知后端: {provider}，可用: {', '.join(CLIENTS.keys())}"
        )
    return cls(config)
