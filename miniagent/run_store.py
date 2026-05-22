"""运行记录存储：保存每次 agent 请求的 trace、状态和摘要。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from .security import redact_obj


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_obj(obj):
    """递归清理不能写入 JSON 的字符。"""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(obj, list):
        return [_clean_obj(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): _clean_obj(value) for key, value in obj.items()}
    return obj


class RunStore:
    """一次用户请求对应一个 run，所有过程事件都落到 `.mini/runs/`。"""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or Path.cwd() / ".mini" / "runs")
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def new_run_id() -> str:
        return "run_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    def run_dir(self, run_id: str) -> Path:
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def append_trace(self, run_id: str, event_type: str, payload: dict | None = None) -> None:
        event = {
            "timestamp": _now(),
            "type": event_type,
        }
        event.update(_clean_obj(redact_obj(payload or {})))
        path = self.run_dir(run_id) / "trace.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def write_status(self, run_id: str, status: dict) -> None:
        payload = {
            "updated_at": _now(),
            **_clean_obj(redact_obj(status)),
        }
        path = self.run_dir(run_id) / "task_status.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_report(self, run_id: str, report: dict) -> None:
        payload = {
            "created_at": _now(),
            **_clean_obj(redact_obj(report)),
        }
        path = self.run_dir(run_id) / "report.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
