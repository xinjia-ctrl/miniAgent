from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from pydantic import BaseModel, Field

from miniagent.utils.diff import unified_diff
from miniagent.utils.ids import new_id


class ChangeRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("chg"))
    session_id: str
    tool_name: str
    path: str
    relative_path: str
    before_exists: bool
    after_exists: bool
    before_path: str | None = None
    after_path: str | None = None
    diff: str = ""
    created_at: float = Field(default_factory=time.time)
    reverted_at: float | None = None

    @property
    def reverted(self) -> bool:
        return self.reverted_at is not None


class RevertResult(BaseModel):
    change_id: str
    path: str
    restored: bool
    message: str


class ChangeStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.changes_dir = self.root / "changes"
        self.index_path = self.changes_dir / "index.json"

    def record_change(
        self,
        *,
        session_id: str,
        tool_name: str,
        cwd: str | Path,
        path: str | Path,
        before_content: str | None,
        after_content: str | None,
        diff: str = "",
    ) -> ChangeRecord:
        target = Path(path).resolve(strict=False)
        record = ChangeRecord(
            session_id=session_id,
            tool_name=tool_name,
            path=str(target),
            relative_path=self._relative_path(cwd, target),
            before_exists=before_content is not None,
            after_exists=after_content is not None,
            diff=diff,
        )
        change_dir = self.changes_dir / record.id
        change_dir.mkdir(parents=True, exist_ok=True)
        if before_content is not None:
            before_path = change_dir / "before.txt"
            before_path.write_text(before_content, encoding="utf-8")
            record.before_path = str(before_path)
        if after_content is not None:
            after_path = change_dir / "after.txt"
            after_path.write_text(after_content, encoding="utf-8")
            record.after_path = str(after_path)
        records = self.list_changes()
        records.append(record)
        self._save(records)
        return record

    def list_changes(self) -> list[ChangeRecord]:
        if not self.index_path.exists():
            return []
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        return [ChangeRecord.model_validate(item) for item in raw]

    def get(self, change_id: str) -> ChangeRecord:
        for record in self.list_changes():
            if record.id == change_id:
                return record
        raise KeyError(f"未知变更：{change_id}")

    def revert(self, change_id: str, *, cwd: str | Path | None = None) -> RevertResult:
        records = self.list_changes()
        for index, record in enumerate(records):
            if record.id != change_id:
                continue
            if record.reverted:
                return RevertResult(
                    change_id=record.id,
                    path=record.path,
                    restored=False,
                    message="该变更已经回滚过",
                )
            target = self._checked_target(record, cwd)
            if record.before_exists:
                if not record.before_path:
                    raise ValueError("checkpoint 缺少 before 快照")
                content = Path(record.before_path).read_text(encoding="utf-8")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                message = f"已恢复文件：{record.relative_path}"
            else:
                if target.exists():
                    deleted = self._remove_file(target)
                    message = (
                        f"已删除新增文件：{record.relative_path}"
                        if deleted
                        else f"删除新增文件受限，已清空内容：{record.relative_path}"
                    )
                else:
                    message = f"新增文件已不存在：{record.relative_path}"
            record.reverted_at = time.time()
            records[index] = record
            self._save(records)
            return RevertResult(
                change_id=record.id,
                path=record.path,
                restored=True,
                message=message,
            )
        raise KeyError(f"未知变更：{change_id}")

    def revert_many(self, change_ids: list[str], *, cwd: str | Path | None = None) -> list[RevertResult]:
        results: list[RevertResult] = []
        for change_id in reversed(change_ids):
            results.append(self.revert(change_id, cwd=cwd))
        return results

    def describe(self, change_id: str | None = None, *, limit: int = 20) -> str:
        if change_id:
            record = self.get(change_id)
            status = "reverted" if record.reverted else "active"
            diff = record.diff or self._diff_from_snapshots(record)
            return (
                f"id: {record.id}\n"
                f"status: {status}\n"
                f"path: {record.relative_path}\n"
                f"tool: {record.tool_name}\n"
                f"created_at: {record.created_at:.3f}\n"
                f"diff:\n{diff}"
            )
        records = list(reversed(self.list_changes()))[:limit]
        if not records:
            return "没有记录的文件变更。"
        lines = []
        for record in records:
            status = "reverted" if record.reverted else "active"
            lines.append(f"{record.id}\t{status}\t{record.tool_name}\t{record.relative_path}")
        return "\n".join(lines)

    def _save(self, records: list[ChangeRecord]) -> None:
        self.changes_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps([record.model_dump(mode="json") for record in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _relative_path(cwd: str | Path, target: Path) -> str:
        root = Path(cwd).resolve(strict=False)
        try:
            return str(target.relative_to(root))
        except ValueError:
            return str(target)

    @staticmethod
    def _checked_target(record: ChangeRecord, cwd: str | Path | None) -> Path:
        target = Path(record.path).resolve(strict=False)
        if cwd is None:
            return target
        root = Path(cwd).resolve(strict=False)
        try:
            common = os.path.commonpath([str(root), str(target)])
        except ValueError as exc:
            raise ValueError("变更路径不在当前工作区内") from exc
        if common != str(root):
            raise ValueError("变更路径不在当前工作区内")
        return target

    @staticmethod
    def _diff_from_snapshots(record: ChangeRecord) -> str:
        before = Path(record.before_path).read_text(encoding="utf-8") if record.before_path else ""
        after = Path(record.after_path).read_text(encoding="utf-8") if record.after_path else ""
        return unified_diff(before, after, fromfile=record.relative_path, tofile=record.relative_path)

    @staticmethod
    def _remove_file(path: Path) -> bool:
        try:
            path.unlink()
            return True
        except PermissionError:
            try:
                path.chmod(stat.S_IWRITE)
                path.unlink()
                return True
            except PermissionError:
                path.write_text("", encoding="utf-8")
                return False
