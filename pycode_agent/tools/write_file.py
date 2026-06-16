from __future__ import annotations

from pydantic import BaseModel

from pycode_agent.tool_base import BaseTool, ToolContext, ToolResult
from pycode_agent.utils.diff import unified_diff
from pycode_agent.utils.paths import resolve_workspace_path


class WriteFileInput(BaseModel):
    file_path: str
    content: str


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "新建或覆盖工作区内的文本文件。覆盖已有文件前必须完整读取过。"
    input_model = WriteFileInput

    async def call(self, input_data: BaseModel, context: ToolContext) -> ToolResult:
        args = WriteFileInput.model_validate(input_data)
        path = resolve_workspace_path(context.cwd, args.file_path, allow_missing=True)
        old = ""
        if path.exists():
            old = path.read_text(encoding="utf-8")
            try:
                _ensure_fresh_read(path, context)
            except ValueError as exc:
                return ToolResult(display=str(exc), is_error=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        diff = unified_diff(old, args.content, fromfile=str(path), tofile=str(path))
        path.write_text(args.content, encoding="utf-8")
        stat = path.stat()
        context.file_reads[str(path)] = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
        return ToolResult(display=diff or f"已写入文件：{path}", structured_content={"path": str(path)})


def _ensure_fresh_read(path, context: ToolContext) -> None:
    record = context.file_reads.get(str(path))
    if not record:
        raise ValueError("覆盖已有文件前必须先完整读取该文件")
    stat = path.stat()
    if record.get("mtime_ns") != stat.st_mtime_ns or record.get("size") != stat.st_size:
        raise ValueError("文件在读取后发生变化，拒绝覆盖")
