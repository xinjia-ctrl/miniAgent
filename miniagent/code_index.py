from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field, computed_field

from miniagent.utils.paths import relative_to_workspace, resolve_workspace_path
from miniagent.utils.text import is_probably_binary_file


EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".mini",
    ".miniagent",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "miniAgent.egg-info",
    "node_modules",
    "test_workspaces",
    "venv",
}

CODE_LANGUAGES = {
    ".c": "c",
    ".cc": "cpp",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".scala": "scala",
    ".sh": "shell",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
}

MAX_CODE_FILE_BYTES = 300_000


class CodeSymbol(BaseModel):
    name: str
    kind: str
    path: str
    line: int
    language: str
    end_line: int | None = None
    container: str | None = None
    signature: str | None = None
    summary: str | None = None

    @computed_field
    @property
    def qualified_name(self) -> str:
        return f"{self.container}.{self.name}" if self.container else self.name


class CodeFileSummary(BaseModel):
    path: str
    language: str
    line_count: int
    symbol_count: int
    symbols: list[CodeSymbol] = Field(default_factory=list)


class CodeIndex(BaseModel):
    root: str
    path: str
    files: list[CodeFileSummary] = Field(default_factory=list)
    symbol_count: int = 0
    language_counts: dict[str, int] = Field(default_factory=dict)
    skipped_files: list[str] = Field(default_factory=list)


def build_code_index(
    cwd: str | Path,
    path: str | Path = ".",
    *,
    max_files: int = 200,
    max_symbols: int = 1200,
) -> CodeIndex:
    root = resolve_workspace_path(cwd, ".", allow_missing=False)
    base = resolve_workspace_path(cwd, path, allow_missing=False)
    files: list[CodeFileSummary] = []
    skipped: list[str] = []
    total_symbols = 0

    for code_path in _iter_code_files(root, base):
        if len(files) >= max_files:
            skipped.append("<max_files reached>")
            break
        relative_path = _relative_path(root, code_path)
        language = CODE_LANGUAGES[code_path.suffix.lower()]
        try:
            source = code_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(relative_path)
            continue

        symbols = parse_symbols(source, path=relative_path, language=language)
        remaining_symbols = max(0, max_symbols - total_symbols)
        if len(symbols) > remaining_symbols:
            symbols = symbols[:remaining_symbols]
            skipped.append(f"{relative_path}:<max_symbols reached>")
        total_symbols += len(symbols)
        files.append(
            CodeFileSummary(
                path=relative_path,
                language=language,
                line_count=len(source.splitlines()),
                symbol_count=len(symbols),
                symbols=symbols,
            )
        )
        if total_symbols >= max_symbols:
            skipped.append("<max_symbols reached>")
            break

    language_counts = Counter(file.language for file in files)
    return CodeIndex(
        root=str(root),
        path=_relative_path(root, base) if base != root else ".",
        files=files,
        symbol_count=sum(file.symbol_count for file in files),
        language_counts=dict(language_counts),
        skipped_files=skipped,
    )


def parse_symbols(source: str, *, path: str, language: str) -> list[CodeSymbol]:
    if language == "python":
        return _parse_python_symbols(source, path=path)
    return _parse_text_symbols(source, path=path, language=language)


def search_symbols(
    index: CodeIndex,
    query: str,
    *,
    kind: str | None = None,
    case_sensitive: bool = False,
    max_results: int = 50,
) -> list[CodeSymbol]:
    needle = query if case_sensitive else query.lower()
    matches: list[tuple[int, CodeSymbol]] = []
    for symbol in _all_symbols(index):
        if kind and symbol.kind != kind:
            continue
        haystacks = [symbol.name, symbol.qualified_name, symbol.path]
        values = haystacks if case_sensitive else [value.lower() for value in haystacks]
        score = _symbol_score(needle, values)
        if score is not None:
            matches.append((score, symbol))
    matches.sort(key=lambda item: (item[0], item[1].path, item[1].line))
    return [symbol for _, symbol in matches[:max_results]]


def format_repo_map(index: CodeIndex, *, max_symbols_per_file: int = 8) -> str:
    lines = [
        "# Repo Map",
        "",
        f"- path: `{index.path}`",
        f"- files: {len(index.files)}",
        f"- symbols: {index.symbol_count}",
        f"- languages: {_format_counts(index.language_counts)}",
        "",
    ]
    current_dir = ""
    for file in index.files:
        directory = _directory_name(file.path)
        if directory != current_dir:
            current_dir = directory
            lines.append(f"{directory}/")
        name = Path(file.path).name
        lines.append(
            f"  - {name} ({file.language}, {file.line_count} lines, "
            f"{file.symbol_count} symbols)"
        )
        for symbol in file.symbols[:max_symbols_per_file]:
            lines.append(f"    - {_format_symbol_brief(symbol)}")
        if file.symbol_count > max_symbols_per_file:
            omitted = file.symbol_count - max_symbols_per_file
            lines.append(f"    - ... omitted {omitted} symbols")
    if index.skipped_files:
        lines.extend(["", "Skipped:"])
        lines.extend(f"- {item}" for item in index.skipped_files[:20])
    return "\n".join(lines) + "\n"


def format_code_index(index: CodeIndex, *, include_symbols: bool = True) -> str:
    lines = [
        "# Code Index",
        "",
        f"- path: `{index.path}`",
        f"- files: {len(index.files)}",
        f"- symbols: {index.symbol_count}",
        f"- languages: {_format_counts(index.language_counts)}",
        "",
    ]
    for file in index.files:
        lines.append(
            f"- {file.path} [{file.language}] lines={file.line_count} "
            f"symbols={file.symbol_count}"
        )
        if include_symbols:
            for symbol in file.symbols:
                lines.append(f"  - {_format_symbol_brief(symbol)}")
    if index.skipped_files:
        lines.extend(["", "Skipped:"])
        lines.extend(f"- {item}" for item in index.skipped_files[:20])
    return "\n".join(lines) + "\n"


def format_symbol_results(symbols: list[CodeSymbol]) -> str:
    if not symbols:
        return "没有找到匹配符号。\n"
    lines = ["# Symbol Search", ""]
    for symbol in symbols:
        summary = f" - {symbol.summary}" if symbol.summary else ""
        lines.append(
            f"- {symbol.path}:{symbol.line} "
            f"{symbol.kind} {symbol.qualified_name}{summary}"
        )
    return "\n".join(lines) + "\n"


def symbol_context_lines(symbols: Iterable[CodeSymbol], *, limit: int = 30) -> list[str]:
    lines = []
    for symbol in symbols:
        summary = f" - {symbol.summary}" if symbol.summary else ""
        lines.append(
            f"{symbol.path}:{symbol.line} {symbol.kind} {symbol.qualified_name}{summary}"
        )
        if len(lines) >= limit:
            break
    return lines


def repo_context_lines(index: CodeIndex, *, limit: int = 30) -> list[str]:
    lines = []
    for file in index.files:
        lines.append(f"{file.path} [{file.language}] symbols={file.symbol_count}")
        for symbol in file.symbols[:4]:
            lines.append(f"  {_format_symbol_brief(symbol)}")
        if len(lines) >= limit:
            return lines[:limit]
    return lines


def _iter_code_files(root: Path, base: Path):
    candidates = [base] if base.is_file() else base.rglob("*")
    for path in sorted(candidates, key=lambda item: _relative_path(root, item)):
        if not path.is_file():
            continue
        if _is_excluded(path, root):
            continue
        if path.suffix.lower() not in CODE_LANGUAGES:
            continue
        if path.stat().st_size > MAX_CODE_FILE_BYTES:
            continue
        if is_probably_binary_file(path):
            continue
        yield path


def _parse_python_symbols(source: str, *, path: str) -> list[CodeSymbol]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    symbols: list[CodeSymbol] = []

    def visit_body(body: list[ast.stmt], container: str | None = None) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                symbol = _python_symbol(
                    node,
                    path=path,
                    kind="class",
                    container=container,
                    lines=lines,
                )
                symbols.append(symbol)
                next_container = symbol.qualified_name
                visit_body(node.body, container=next_container)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    _python_symbol(
                        node,
                        path=path,
                        kind="method" if container else "function",
                        container=container,
                        lines=lines,
                    )
                )

    visit_body(tree.body)
    return symbols


def _python_symbol(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    path: str,
    kind: str,
    container: str | None,
    lines: list[str],
) -> CodeSymbol:
    docstring = ast.get_docstring(node)
    return CodeSymbol(
        name=node.name,
        kind=kind,
        path=path,
        line=node.lineno,
        end_line=getattr(node, "end_lineno", None),
        container=container,
        signature=_line_at(lines, node.lineno),
        summary=_first_sentence(docstring),
        language="python",
    )


def _parse_text_symbols(source: str, *, path: str, language: str) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        for kind, pattern in _patterns_for(language):
            match = pattern.search(stripped)
            if not match:
                continue
            name = next((value for value in match.groups() if value), "")
            if name:
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind=kind,
                        path=path,
                        line=line_no,
                        language=language,
                        signature=stripped[:180],
                    )
                )
                break
    return symbols


def _patterns_for(language: str) -> list[tuple[str, re.Pattern[str]]]:
    identifier = r"([A-Za-z_$][\w$]*)"
    common_class = re.compile(rf"(?:export\s+)?(?:class|interface|enum|trait)\s+{identifier}")
    if language in {"javascript", "typescript"}:
        return [
            ("class", common_class),
            ("type", re.compile(rf"(?:export\s+)?type\s+{identifier}\b")),
            ("function", re.compile(rf"(?:export\s+)?(?:async\s+)?function\s+{identifier}\b")),
            ("function", re.compile(rf"(?:const|let|var)\s+{identifier}\s*=\s*(?:async\s*)?")),
        ]
    if language == "go":
        return [
            ("function", re.compile(rf"func\s+(?:\([^)]*\)\s*)?{identifier}\s*\(")),
            ("type", re.compile(rf"type\s+{identifier}\s+(?:struct|interface)\b")),
        ]
    if language == "rust":
        return [
            ("function", re.compile(rf"(?:pub\s+)?fn\s+{identifier}\b")),
            ("class", re.compile(rf"(?:pub\s+)?(?:struct|enum|trait)\s+{identifier}\b")),
        ]
    if language in {"java", "csharp", "kotlin", "scala", "swift", "php", "ruby"}:
        return [
            ("class", common_class),
            ("function", re.compile(rf"(?:fun|func|def|function)\s+{identifier}\b")),
        ]
    if language in {"c", "cpp"}:
        return [
            ("class", re.compile(rf"(?:class|struct|enum)\s+{identifier}\b")),
            ("function", re.compile(rf"[A-Za-z_][\w:<>,~*&\s]+\s+{identifier}\s*\([^;]*\)\s*\{{?")),
        ]
    if language == "shell":
        return [
            ("function", re.compile(rf"(?:function\s+)?{identifier}\s*\(\)\s*\{{?")),
        ]
    return []


def _all_symbols(index: CodeIndex):
    for file in index.files:
        yield from file.symbols


def _symbol_score(needle: str, values: list[str]) -> int | None:
    for value in values:
        if value == needle:
            return 0
    for value in values:
        if value.startswith(needle):
            return 1
    for value in values:
        if needle in value:
            return 2
    return None


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve(strict=False).relative_to(root).parts
    except ValueError:
        return True
    return any(part in EXCLUDED_DIRS for part in parts)


def _relative_path(root: Path, path: Path) -> str:
    return relative_to_workspace(root, path).replace("\\", "/")


def _directory_name(path: str) -> str:
    directory = str(Path(path).parent).replace("\\", "/")
    return "." if directory in {"", "."} else directory


def _line_at(lines: list[str], line_no: int) -> str:
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()[:180]
    return ""


def _first_sentence(value: str | None) -> str | None:
    if not value:
        return None
    first_line = value.strip().splitlines()[0].strip()
    return first_line[:180] if first_line else None


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "<none>"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def _format_symbol_brief(symbol: CodeSymbol) -> str:
    summary = f" - {symbol.summary}" if symbol.summary else ""
    return f"{symbol.kind} {symbol.qualified_name} L{symbol.line}{summary}"
