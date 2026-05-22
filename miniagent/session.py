"""会话管理：创建、保存、加载、列出、删除"""

import json
import uuid
from datetime import datetime
from pathlib import Path

# 会话存储目录（基于当前工作目录，按项目隔离）
SESSION_DIR = Path.cwd() / ".mini" / "sessions"


def _session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_obj(obj):
    """递归移除 surrogate 字符，避免 JSON 写入时报错"""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(obj, list):
        return [_clean_obj(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _clean_obj(value) for key, value in obj.items()}
    return obj


def list_sessions() -> list[dict]:
    """列出所有历史会话，按时间倒序"""
    if not SESSION_DIR.exists():
        return []
    sessions = []
    for f in sorted(SESSION_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "id": f.stem,
                "title": data.get("title", "未命名"),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "message_count": len(data.get("messages", [])),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def create_session(title: str = "新会话") -> str:
    """创建新会话，返回 session_id"""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_id = uuid.uuid4().hex[:12]
    data = {
        "title": title,
        "created_at": _now(),
        "updated_at": _now(),
        "messages": [],
    }
    _session_path(session_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return session_id


def save_message(session_id: str, role: str, content: str = "", **extra) -> None:
    """保存一条消息到会话，支持 tool_calls/tool_call_id 等结构化字段"""
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"会话不存在: {session_id}")

    data = json.loads(path.read_text(encoding="utf-8"))
    message = {
        "role": role,
        "content": _clean_obj(content or ""),
        "timestamp": _now(),
    }
    for key, value in extra.items():
        if value is not None:
            message[key] = _clean_obj(value)

    data["messages"].append(message)
    data["updated_at"] = _now()
    # 自动用第一条用户消息当标题
    if data["title"] == "新会话" and role == "user":
        data["title"] = content[:30] + ("..." if len(content) > 30 else "")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_messages(session_id: str) -> list[dict]:
    """加载会话消息列表"""
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"会话不存在: {session_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("messages", [])


def get_session(session_id: str) -> dict:
    """获取会话元信息"""
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"会话不存在: {session_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "id": session_id,
        "title": data.get("title", "未命名"),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
        "message_count": len(data.get("messages", [])),
    }


def delete_session(session_id: str) -> None:
    """删除会话"""
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"会话不存在: {session_id}")
    path.unlink()


def rename_session(session_id: str, title: str) -> None:
    """重命名会话"""
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"会话不存在: {session_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["title"] = title
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    # 简单测试
    sid = create_session("测试会话")
    print(f"创建会话: {sid}")
    save_message(sid, "user", "你好")
    save_message(sid, "assistant", "你好！我是 miniAgent")
    save_message(sid, "user", "今天天气怎么样")
    save_message(sid, "assistant", "我是本地助手，无法查天气")
    print(f"消息数: {len(load_messages(sid))}")
    print(f"会话列表: {list_sessions()}")
    delete_session(sid)
    print("删除成功")
