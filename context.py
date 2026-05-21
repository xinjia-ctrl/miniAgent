# context.py - 阶段五
# 上下文预算管理：裁剪 messages 列表使其不超出模型窗口

TOTAL_BUDGET = 12000   # 总字符数上限（约 6000 tokens）

# 各部分字符数配额
SECTION_BUDGETS = {
    "prefix": 3600,    # 系统指令 + tools 定义
    "history": 5200,   # 对话历史
    "request": 0,      # 最新用户请求（永不裁剪）
}

SECTION_FLOORS = {
    "prefix": 1200,    # 至少保留工具定义
    "history": 1500,   # 至少保留最近几条对话
}

REDUCTION_ORDER = ["history", "prefix"]


def _char_len(text):
    """安全的字符数计算"""
    return len(str(text))


def _tail_clip(text, limit):
    """从尾部裁剪，超限部分用 ... 替代"""
    text = str(text)
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[:limit-3] + "..."


def trim_messages(messages):
    """按预算裁剪 messages 列表，适配 function calling

    规则：
    - request：最新一条 user 消息永不裁剪
    - prefix：系统消息内容超预算时从尾部裁剪
    - history：从旧到新丢弃，保留最近的
    - 裁剪优先级：history > prefix
    - 各部分有保底下限
    """
    if not messages:
        return messages

    # 分离各部分
    system_msgs = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]

    # 保护最后一条 user 消息
    last_user_idx = None
    for i in range(len(others) - 1, -1, -1):
        if others[i].get("role") == "user":
            last_user_idx = i
            break

    request_msg = others.pop(last_user_idx) if last_user_idx is not None else None
    history = others  # 剩下的都是历史

    budgets = dict(SECTION_BUDGETS)

    # 1. 裁剪 prefix（系统消息内容）
    for sm in system_msgs:
        content = sm.get("content", "") or ""
        budget = max(budgets.get("prefix", 3600), SECTION_FLOORS.get("prefix", 0))
        if _char_len(content) > budget:
            sm["content"] = _tail_clip(content, budget)

    # 2. 裁剪 history：从旧到新丢弃，直到符合预算
    budget = max(budgets.get("history", 5200), SECTION_FLOORS.get("history", 0))
    # 先估算当前总长度
    history_len = sum(_char_len(m.get("content", "") or "") for m in history)

    # 如果还是超，从旧的开始丢弃整条消息
    while history and history_len > budget:
        removed = history.pop(0)
        history_len -= _char_len(removed.get("content", "") or "")
        # 如果丢完还不够就继续丢

    # 如果某条消息自身超长，裁剪它
    for i, m in enumerate(history):
        content = m.get("content", "") or ""
        # 每条历史消息不超过预算的 60%
        per_msg_budget = int(budget * 0.6)
        if _char_len(content) > per_msg_budget:
            history[i]["content"] = _tail_clip(content, per_msg_budget)

    # 3. 重新组装
    result = list(system_msgs)
    result.extend(history)
    if request_msg:
        result.append(request_msg)  # 永不裁剪

    # 4. 如果整体仍然超 TOTAL_BUDGET，按优先级继续压缩
    total_len = sum(_char_len(m.get("content", "") or "") for m in result)
    while total_len > TOTAL_BUDGET:
        reduced = False

        # 按优先级裁
        for section in REDUCTION_ORDER:
            if section == "history":
                # 找历史消息，从旧到新逐步裁剪
                history_msgs = [m for m in result if m.get("role") in ("user", "assistant", "tool")]
                history_msgs = [m for m in history_msgs if m is not request_msg]
                if history_msgs:
                    # 裁剪最旧的一条的内容
                    target = history_msgs[0]
                    for idx, m in enumerate(result):
                        if m is target:
                            content = m.get("content", "") or ""
                            new_content = _tail_clip(content, int(_char_len(content) * 0.7))
                            result[idx]["content"] = new_content
                            reduced = True
                            break
                    if reduced:
                        break

            elif section == "prefix":
                for sm in system_msgs:
                    for idx, m in enumerate(result):
                        if m is sm:
                            content = m.get("content", "") or ""
                            floor = SECTION_FLOORS.get("prefix", 0)
                            current = _char_len(content)
                            if current > floor:
                                result[idx]["content"] = _tail_clip(content, floor)
                                reduced = True
                                break
                    if reduced:
                        break
            if reduced:
                break

        total_len = sum(_char_len(m.get("content", "") or "") for m in result)
        if not reduced:
            break

    return result
