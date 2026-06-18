from __future__ import annotations

from miniagent.code_index import build_code_index, search_symbols
from miniagent.tool_base import ToolContext
from miniagent.tools.code_understanding import (
    CodeIndexInput,
    CodeIndexTool,
    RepoMapInput,
    RepoMapTool,
    SymbolSearchInput,
    SymbolSearchTool,
)


def test_code_index_extracts_python_symbols_and_skips_generated_dirs(tmp_path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "\n".join(
            [
                "class Greeter:",
                "    \"\"\"负责问候。\"\"\"",
                "    def greet(self, name: str) -> str:",
                "        return f'hi {name}'",
                "",
                "def run():",
                "    return Greeter().greet('agent')",
            ]
        ),
        encoding="utf-8",
    )
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "fake.py").write_text("class Ignored: pass\n", encoding="utf-8")

    index = build_code_index(tmp_path)
    symbols = [symbol.qualified_name for file in index.files for symbol in file.symbols]
    hits = search_symbols(index, "greet")

    assert [file.path for file in index.files] == ["src/app.py"]
    assert "Greeter" in symbols
    assert "Greeter.greet" in symbols
    assert "run" in symbols
    assert hits[0].qualified_name == "Greeter.greet"
    assert hits[0].summary is None
    assert index.files[0].symbols[0].summary == "负责问候。"


async def test_code_understanding_tools_return_structured_index(tmp_path) -> None:
    (tmp_path / "service.py").write_text(
        "class Service:\n"
        "    \"\"\"业务服务。\"\"\"\n"
        "    def handle(self):\n"
        "        return 'ok'\n",
        encoding="utf-8",
    )
    context = ToolContext(
        cwd=str(tmp_path),
        session_id="sess_repo_map",
        permission_mode="default",
        state={},
    )

    repo = await RepoMapTool().call(RepoMapInput(), context)
    search = await SymbolSearchTool().call(SymbolSearchInput(query="handle"), context)
    index = await CodeIndexTool().call(CodeIndexInput(include_symbols=False), context)

    assert "Repo Map" in repo.display
    assert "Service.handle" in search.display
    assert index.structured_content is not None
    assert index.structured_content["index"]["files"][0]["path"] == "service.py"
    assert "symbols" not in index.structured_content["index"]["files"][0]
    assert context.state["last_code_context"]["title"] == "code_index"
