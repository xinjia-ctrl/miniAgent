from __future__ import annotations

from pydantic import BaseModel

from miniagent.changes import ChangeStore
from miniagent.tool_base import BaseTool, ToolContext, ToolResult
from miniagent.utils.diff import unified_diff
from miniagent.utils.paths import resolve_workspace_path


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
        old: str | None = None
        if path.exists():
            old = path.read_text(encoding="utf-8")
            try:
                _ensure_fresh_read(path, context)
            except ValueError as exc:
                return ToolResult(display=str(exc), is_error=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        diff = unified_diff(old or "", args.content, fromfile=str(path), tofile=str(path))
        change = _record_change(
            context,
            tool_name=self.name,
            path=path,
            before_content=old,
            after_content=args.content,
            diff=diff,
        )
        path.write_text(args.content, encoding="utf-8")
        stat = path.stat()
        context.file_reads[str(path)] = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
        structured = {"path": str(path)}
        if change:
            structured["change_id"] = change.id
        return ToolResult(display=diff or f"已写入文件：{path}", structured_content=structured)


def _ensure_fresh_read(path, context: ToolContext) -> None:
    record = context.file_reads.get(str(path))
    if not record:
        raise ValueError("覆盖已有文件前必须先完整读取该文件")
    stat = path.stat()
    if record.get("mtime_ns") != stat.st_mtime_ns or record.get("size") != stat.st_size:
        raise ValueError("文件在读取后发生变化，拒绝覆盖")


def _record_change(
    context: ToolContext,
    *,
    tool_name: str,
    path,
    before_content: str | None,
    after_content: str | None,
    diff: str,
):
    data_dir = context.data_dir or str(resolve_workspace_path(context.cwd, ".miniagent", allow_missing=True))
    change = ChangeStore(data_dir).record_change(
        session_id=context.session_id,
        tool_name=tool_name,
        cwd=context.cwd,
        path=path,
        before_content=before_content,
        after_content=after_content,
        diff=diff,
    )
    context.state.setdefault("changes", []).append(
        {
            "id": change.id,
            "path": change.relative_path,
            "tool": change.tool_name,
            "created_at": change.created_at,
        }
    )
    return change
