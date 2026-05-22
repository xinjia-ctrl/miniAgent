"""审计日志：记录会话、工具调用和审批操作"""

import json
from datetime import datetime
from pathlib import Path
from .security import redact_obj, redact_text

LOG_DIR = Path.cwd() / ".mini" / "logs"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_obj(obj):
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(obj, list):
        return [_clean_obj(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): _clean_obj(value) for key, value in obj.items()}
    return obj


def _summarize_args(args):
    """压缩参数，避免日志里塞入大段文件内容"""
    result = {}
    for key, value in (args or {}).items():
        if key in ("content", "old_text", "new_text"):
            text = str(value)
            result[key] = {
                "length": len(text),
                "preview": text[:120],
            }
        elif key == "patches" and isinstance(value, list):
            result[key] = [
                {
                    "path": item.get("path"),
                    "old_text_length": len(str(item.get("old_text", ""))),
                    "new_text_length": len(str(item.get("new_text", ""))),
                    "expected_replacements": item.get("expected_replacements", 1),
                }
                for item in value
                if isinstance(item, dict)
            ]
        else:
            result[key] = value
    return result


def log_event(event_type, session_id=None, **payload):
    """写入 JSONL 审计日志"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    event = {
        "timestamp": _now(),
        "type": event_type,
        "session_id": session_id,
    }
    event.update(_clean_obj(redact_obj(payload)))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def log_tool_call(session_id, name, args):
    log_event(
        "tool_call",
        session_id=session_id,
        name=name,
        args=_summarize_args(args),
    )


def log_tool_result(session_id, name, result):
    text = str(result)
    log_event(
        "tool_result",
        session_id=session_id,
        name=name,
        result={
            "length": len(text),
            "preview": redact_text(text[:500]),
        },
    )
