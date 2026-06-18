from __future__ import annotations

import pytest

from miniagent.tool_base import ToolRegistry
from miniagent.tools import builtin_registry
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


def test_builtin_registry_includes_code_understanding_tools() -> None:
    names = set(builtin_registry().names())

    assert {"repo_map", "symbol_search", "code_index"}.issubset(names)
