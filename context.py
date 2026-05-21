# context.py - 阶段五
# 上下文预算管理：裁剪 messages 列表使其不超出模型窗口

import copy
import json

TOTAL_BUDGET = 12000   # 总字符数上限（约 6000 tokens）

# 各部分字符数配额
SECTION_BUDGETS = {
    "prefix": 3600,    # 系统指令 + 工作区快照
    "history": 5200,   # 对话历史
}

SECTION_FLOORS = {
    "prefix": 1200,    # 至少保留核心系统指令
    "history": 1500,   # 至少保留最近几轮对话
}


def _char_len(value):
    """估算消息长度，包含 tool_calls 等结构化字段"""
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except TypeError:
        return len(str(value))


def _tail_clip(text, limit):
    """从尾部裁剪，超限部分用 ... 替代"""
    text = str(text)
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[:limit - 3] + "..."


def _group_messages(messages):
    """把 assistant tool_calls 和紧随其后的 tool 结果组成不可拆分的组"""
    groups = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        group = [msg]

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tool_ids = {tc.get("id") for tc in msg.get("tool_calls", [])}
            i += 1
            while i < len(messages):
                next_msg = messages[i]
                if next_msg.get("role") != "tool":
                    break
                tool_call_id = next_msg.get("tool_call_id")
                if tool_ids and tool_call_id not in tool_ids:
                    break
                group.append(next_msg)
                i += 1
            groups.append(group)
            continue

        groups.append(group)
        i += 1

    return groups


def _group_len(group):
    return sum(_char_len(msg) for msg in group)


def _clip_group(group, per_msg_budget):
    """只裁剪 content，不破坏 role/tool_calls/tool_call_id 等结构"""
    for msg in group:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > per_msg_budget:
            msg["content"] = _tail_clip(content, per_msg_budget)


def _flatten(groups):
    result = []
    for group in groups:
        result.extend(group)
    return result


def trim_messages(messages):
    """按预算裁剪 messages，保证 function calling 消息结构完整。

    规则：
    - system 消息只裁 content，不删除。
    - assistant(tool_calls) 和后续 tool 结果作为一个组裁剪/丢弃。
    - 最新一组消息永远保留，避免当前请求或当前工具调用链被破坏。
    """
    if not messages:
        return messages

    cloned = copy.deepcopy(messages)
    system_msgs = [m for m in cloned if m.get("role") == "system"]
    body = [m for m in cloned if m.get("role") != "system"]
    groups = _group_messages(body)

    # 1. 裁剪 system prefix
    prefix_budget = max(SECTION_BUDGETS["prefix"], SECTION_FLOORS["prefix"])
    for sm in system_msgs:
        content = sm.get("content", "") or ""
        if len(content) > prefix_budget:
            sm["content"] = _tail_clip(content, prefix_budget)

    if not groups:
        return system_msgs

    protected = groups[-1]
    history = groups[:-1]
    history_budget = max(SECTION_BUDGETS["history"], SECTION_FLOORS["history"])

    # 2. 历史组从旧到新丢弃，组内结构不拆
    while history and sum(_group_len(g) for g in history) > history_budget:
        history.pop(0)

    # 3. 单组过长时只裁剪 content，保留工具调用结构
    per_msg_budget = max(600, int(history_budget * 0.4))
    for group in history:
        if _group_len(group) > per_msg_budget * max(1, len(group)):
            _clip_group(group, per_msg_budget)

    result = system_msgs + _flatten(history) + protected

    # 4. 总预算仍超时，继续压缩旧历史组；最后才压 system
    while _char_len(result) > TOTAL_BUDGET and history:
        history.pop(0)
        result = system_msgs + _flatten(history) + protected

    if _char_len(result) > TOTAL_BUDGET:
        for sm in system_msgs:
            floor = SECTION_FLOORS["prefix"]
            content = sm.get("content", "") or ""
            if len(content) > floor:
                sm["content"] = _tail_clip(content, floor)
        result = system_msgs + _flatten(history) + protected

    return result
