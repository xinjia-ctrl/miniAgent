from __future__ import annotations

from pycode_agent.messages import Message, TextBlock, ToolUseBlock, message_text, tool_result_message


def test_message_roundtrip_with_tool_use() -> None:
    message = Message(
        role="assistant",
        content=[TextBlock(text="先读文件"), ToolUseBlock(name="read_file", input={"file_path": "README.md"})],
    )

    restored = Message.model_validate_json(message.model_dump_json())

    assert restored.role == "assistant"
    assert isinstance(restored.content[1], ToolUseBlock)
    assert "tool_use:read_file" in message_text(restored)


def test_tool_result_message_is_user_message() -> None:
    message = tool_result_message("tool_1", "ok")

    assert message.role == "user"
    assert message.content[0].type == "tool_result"
