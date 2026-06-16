from __future__ import annotations

from pycode_agent.context import ContextBuilder
from pycode_agent.messages import user_text


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


def test_context_trims_old_messages(config, registry) -> None:
    config.context_token_budget = 20
    messages = [user_text("x" * 100), user_text("last")]

    request = ContextBuilder().build(messages=messages, registry=registry, config=config, state={})

    assert request.messages[-1].content[0].text == "last"
