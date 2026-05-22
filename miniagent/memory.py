# memory.py - 阶段六
# 多层次记忆：工作记忆 + 持久记忆 + 会话摘要

import json
import uuid
import math
import re
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path.cwd() / ".mini" / "memory"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return datetime.now()


def _keywords(text):
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", str(text).lower())
    return sorted({token for token in tokens if len(token) >= 2})


def _ensure_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _path(key):
    return MEMORY_DIR / f"{key}.json"


# ======== 工作记忆（当前会话，易失） ========

WORKING_MEMORY = {}


def set_working(key, value):
    """设置工作记忆（仅当前会话有效）"""
    WORKING_MEMORY[key] = {
        "value": value,
        "updated_at": _now(),
    }


def get_working(key, default=None):
    """读取工作记忆"""
    item = WORKING_MEMORY.get(key)
    return item["value"] if item else default


def clear_working():
    """清空工作记忆"""
    WORKING_MEMORY.clear()


def dump_working():
    """导出工作记忆文本（给 AI 用）"""
    if not WORKING_MEMORY:
        return "- 无"
    lines = []
    for key, item in WORKING_MEMORY.items():
        lines.append(f"  {key}: {item['value']}")
    return "\n" + "\n".join(lines)


# ======== 持久记忆（跨会话，存文件） ========

def remember(tag, content, importance=1, keywords=None):
    """存储一条持久记忆

    importance: 1-5，越高越优先保留
    """
    _ensure_dir()
    mem_id = uuid.uuid4().hex[:8]
    data = {
        "id": mem_id,
        "tag": tag,
        "content": content,
        "keywords": sorted(set(keywords or _keywords(f"{tag} {content}"))),
        "importance": max(1, min(int(importance), 5)),
        "created_at": _now(),
        "updated_at": _now(),
    }
    path = _path(mem_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return mem_id


def recall(tag=None, query=None, limit=10, now=None):
    """检索持久记忆，综合标签、关键词、重要性和时效衰减排序。"""
    _ensure_dir()
    results = []
    for f in MEMORY_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if tag and data.get("tag") != tag:
                continue
            data.setdefault("keywords", _keywords(f"{data.get('tag', '')} {data.get('content', '')}"))
            data["_score"] = score_memory(data, query=query, now=now)
            results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    results.sort(key=lambda x: (x.get("_score", 0), x.get("importance", 0), x.get("updated_at", "")), reverse=True)
    return results[:limit]


def score_memory(item, query=None, now=None):
    """计算记忆召回分数：重要性 + tag/关键词命中 + 时效衰减。"""
    now = now or datetime.now()
    updated = _parse_time(item.get("updated_at") or item.get("created_at"))
    age_days = max(0, (now - updated).days)
    recency = math.exp(-age_days / 30)

    score = float(item.get("importance", 1)) + recency
    if not query:
        return score

    query_terms = set(_keywords(query))
    if not query_terms:
        return score
    tag_terms = set(_keywords(item.get("tag", "")))
    keyword_terms = set(item.get("keywords") or [])
    content_terms = set(_keywords(item.get("content", "")))

    score += 2.0 * len(query_terms & tag_terms)
    score += 1.5 * len(query_terms & keyword_terms)
    score += 0.5 * len(query_terms & content_terms)
    return score


def forget(mem_id):
    """删除单条记忆"""
    path = _path(mem_id)
    if path.exists():
        path.unlink()


def summarize_memories(tags=None, query=None, limit=5):
    """把持久记忆压缩成文本块（给 system prompt 用）"""
    items = recall(tag=tags, query=query, limit=limit) if tags else recall(query=query, limit=limit)
    if not items:
        return ""
    lines = ["【记忆存档】"]
    for item in items:
        keywords = ", ".join(item.get("keywords") or [])
        suffix = f" (keywords: {keywords})" if keywords else ""
        lines.append(f"- [{item['tag']}] {item['content']}{suffix}")
    return "\n".join(lines)


# ======== 会话摘要（压缩历史到一段话） ========

def build_memory_block(tags=None, query=None, mem_limit=5):
    """组装完整记忆文本块，注入 system prompt"""
    parts = []

    # 持久记忆
    mem_text = summarize_memories(tags=tags, query=query, limit=mem_limit)
    if mem_text:
        parts.append(mem_text)

    # 工作记忆
    working = dump_working()
    if working and working != "- 无":
        parts.append(f"【当前状态】{working}")

    return "\n\n".join(parts)


# ======== memory 目录管理 ========

def list_tags():
    """列出所有记忆标签"""
    _ensure_dir()
    tags = set()
    for f in MEMORY_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("tag"):
                tags.add(data["tag"])
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(tags)


def stats():
    """记忆统计"""
    _ensure_dir()
    files = list(MEMORY_DIR.glob("*.json"))
    return {
        "total": len(files),
        "tags": list_tags(),
        "working_keys": list(WORKING_MEMORY.keys()),
    }
