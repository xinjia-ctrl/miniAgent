from __future__ import annotations

import pytest

from miniagent.tool_base import ToolRegistry
from fakes import EchoTool


def test_registry_registers_and_exports_schema() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    assert registry.get("echo").name == "echo"
    assert registry.names() == ["echo"]
    assert registry.tool_schemas()[0]["input_schema"]["properties"]["text"]["type"] == "string"


def test_registry_rejects_duplicate_tool() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(ValueError):
        registry.register(EchoTool())
