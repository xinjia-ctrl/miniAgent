from __future__ import annotations

import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from pycode_agent.utils.ids import new_id


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str = Field(default_factory=lambda: new_id("tool"))
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = Annotated[TextBlock | ToolUseBlock | ToolResultBlock, Field(discriminator="type")]


class Message(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    role: Literal["system", "user", "assistant"]
    content: list[ContentBlock]
    created_at: float = Field(default_factory=time.time)
    meta: dict[str, Any] = Field(default_factory=dict)


def user_text(text: str) -> Message:
    return Message(role="user", content=[TextBlock(text=text)])


def assistant_text(text: str) -> Message:
    return Message(role="assistant", content=[TextBlock(text=text)])


def assistant_message(blocks: list[ContentBlock]) -> Message:
    return Message(role="assistant", content=blocks)


def tool_result_message(tool_use_id: str, content: str, is_error: bool = False) -> Message:
    return Message(
        role="user",
        content=[ToolResultBlock(tool_use_id=tool_use_id, content=content, is_error=is_error)],
    )


def message_text(message: Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            parts.append(f"[tool_use:{block.name}:{block.id}]")
        elif isinstance(block, ToolResultBlock):
            state = "error" if block.is_error else "ok"
            parts.append(f"[tool_result:{state}:{block.tool_use_id}] {block.content}")
    return "\n".join(parts)
