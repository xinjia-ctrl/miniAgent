from __future__ import annotations

from pydantic import BaseModel, Field

from miniagent.code_index import (
    build_code_index,
    format_code_index,
    format_repo_map,
    format_symbol_results,
    repo_context_lines,
    search_symbols,
    symbol_context_lines,
)
from miniagent.tool_base import BaseTool, ToolContext, ToolResult
from miniagent.utils.text import clip_text


class RepoMapInput(BaseModel):
    path: str = "."
    max_files: int = Field(default=120, ge=1, le=500)
    max_symbols_per_file: int = Field(default=8, ge=0, le=30)


class SymbolSearchInput(BaseModel):
    query: str = Field(min_length=1)
    path: str = "."
    kind: str | None = None
    case_sensitive: bool = False
    max_results: int = Field(default=50, ge=1, le=200)


class CodeIndexInput(BaseModel):
    path: str = "."
    max_files: int = Field(default=120, ge=1, le=500)
    max_symbols: int = Field(default=1200, ge=1, le=5000)
    include_symbols: bool = True


class RepoMapTool(BaseTool):
    name = "repo_map"
    description = "生成工作区代码结构地图，按文件展示函数、类和方法摘要。"
    input_model = RepoMapInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = RepoMapInput.model_validate(input_data)
        index = build_code_index(context.cwd, args.path, max_files=args.max_files)
        _remember_code_context(context, "repo_map", repo_context_lines(index))
        return ToolResult(
            display=clip_text(
                format_repo_map(index, max_symbols_per_file=args.max_symbols_per_file),
                context.max_result_chars,
            ),
            structured_content={"index": index.model_dump(mode="json")},
        )


class SymbolSearchTool(BaseTool):
    name = "symbol_search"
    description = "按名称搜索代码符号，返回函数、类、方法的路径、行号和摘要。"
    input_model = SymbolSearchInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = SymbolSearchInput.model_validate(input_data)
        index = build_code_index(context.cwd, args.path, max_files=500, max_symbols=5000)
        matches = search_symbols(
            index,
            args.query,
            kind=args.kind,
            case_sensitive=args.case_sensitive,
            max_results=args.max_results,
        )
        _remember_code_context(
            context,
            f"symbol_search:{args.query}",
            symbol_context_lines(matches),
        )
        return ToolResult(
            display=clip_text(format_symbol_results(matches), context.max_result_chars),
            structured_content={
                "query": args.query,
                "matches": [symbol.model_dump(mode="json") for symbol in matches],
            },
        )


class CodeIndexTool(BaseTool):
    name = "code_index"
    description = "返回结构化代码索引，包含代码文件、语言统计和符号列表。"
    input_model = CodeIndexInput

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = CodeIndexInput.model_validate(input_data)
        index = build_code_index(
            context.cwd,
            args.path,
            max_files=args.max_files,
            max_symbols=args.max_symbols,
        )
        _remember_code_context(context, "code_index", repo_context_lines(index))
        payload = index.model_dump(mode="json")
        if not args.include_symbols:
            payload["files"] = [
                {key: value for key, value in file.items() if key != "symbols"}
                for file in payload["files"]
            ]
        return ToolResult(
            display=clip_text(
                format_code_index(index, include_symbols=args.include_symbols),
                context.max_result_chars,
            ),
            structured_content={"index": payload},
        )


def _remember_code_context(context: ToolContext, title: str, items: list[str]) -> None:
    context.state["last_code_context"] = {
        "title": title,
        "items": items[:30],
    }
