"""上下文预算管理：按分段策略裁剪 messages，并输出可实验指标。"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass

TOTAL_BUDGET = int(os.getenv("MINI_CONTEXT_BUDGET", "240000"))

SECTION_BUDGETS = {
    "prefix": int(os.getenv("MINI_PREFIX_BUDGET", "60000")),
    "history": int(os.getenv("MINI_HISTORY_BUDGET", "160000")),
    "protected": int(os.getenv("MINI_PROTECTED_BUDGET", "30000")),
}

SECTION_FLOORS = {
    "prefix": 12000,
    "history": 30000,
    "protected": 4000,
}


def _char_len(value) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except TypeError:
        return len(str(value))


def _tail_clip(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _flatten(groups):
    result = []
    for group in groups:
        result.extend(group)
    return result


@dataclass
class ContextMetrics:
    before_chars: int
    after_chars: int
    message_count_before: int
    message_count_after: int
    removed_groups: int
    clipped_messages: int
    prefix_clipped: bool

    def to_dict(self):
        return {
            "before_chars": self.before_chars,
            "after_chars": self.after_chars,
            "removed_chars": max(0, self.before_chars - self.after_chars),
            "message_count_before": self.message_count_before,
            "message_count_after": self.message_count_after,
            "removed_groups": self.removed_groups,
            "clipped_messages": self.clipped_messages,
            "prefix_clipped": self.prefix_clipped,
            "trimmed": self.after_chars <= self.before_chars,
        }


class ContextBudgeter:
    """把 system prefix、历史组和最新请求分开预算。

    关键约束：
    - system prefix 只裁剪 content，不删除。
    - assistant(tool_calls) 和后续 tool 结果作为不可拆分组。
    - 最新一组消息受 protected 预算保护，避免当前请求或工具链被丢。
    """

    def __init__(self, total_budget=None, section_budgets=None, section_floors=None):
        self.total_budget = int(total_budget or TOTAL_BUDGET)
        self.section_budgets = dict(SECTION_BUDGETS)
        if section_budgets:
            self.section_budgets.update({str(key): int(value) for key, value in section_budgets.items()})
        self.section_floors = dict(SECTION_FLOORS)
        if section_floors:
            self.section_floors.update({str(key): int(value) for key, value in section_floors.items()})

    def trim(self, messages):
        if not messages:
            metrics = ContextMetrics(0, 0, 0, 0, 0, 0, False)
            return messages, metrics.to_dict()

        before_chars = _char_len(messages)
        cloned = copy.deepcopy(messages)
        system_msgs = [m for m in cloned if m.get("role") == "system"]
        body = [m for m in cloned if m.get("role") != "system"]
        groups = self.group_messages(body)

        prefix_clipped = self._trim_prefix(system_msgs)
        if not groups:
            result = system_msgs
            metrics = ContextMetrics(before_chars, _char_len(result), len(messages), len(result), 0, 0, prefix_clipped)
            return result, metrics.to_dict()

        protected = groups[-1]
        history = groups[:-1]
        removed_groups = self._drop_old_history(history)
        clipped_messages = self._clip_oversized_groups(history)
        clipped_messages += self._clip_protected(protected)

        result = system_msgs + _flatten(history) + protected
        while _char_len(result) > self.total_budget and history:
            history.pop(0)
            removed_groups += 1
            result = system_msgs + _flatten(history) + protected

        if _char_len(result) > self.total_budget:
            prefix_clipped = self._trim_prefix(system_msgs, force_floor=True) or prefix_clipped
            result = system_msgs + _flatten(history) + protected

        metrics = ContextMetrics(
            before_chars=before_chars,
            after_chars=_char_len(result),
            message_count_before=len(messages),
            message_count_after=len(result),
            removed_groups=removed_groups,
            clipped_messages=clipped_messages,
            prefix_clipped=prefix_clipped,
        )
        return result, metrics.to_dict()

    @staticmethod
    def group_messages(messages):
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

    def _budget(self, section):
        return max(int(self.section_budgets[section]), int(self.section_floors[section]))

    def _trim_prefix(self, system_msgs, force_floor=False):
        clipped = False
        limit = int(self.section_floors["prefix"] if force_floor else self._budget("prefix"))
        for msg in system_msgs:
            content = msg.get("content", "") or ""
            if len(content) > limit:
                msg["content"] = _tail_clip(content, limit)
                clipped = True
        return clipped

    def _drop_old_history(self, history):
        removed = 0
        history_budget = self._budget("history")
        while history and sum(_char_len(group) for group in history) > history_budget:
            history.pop(0)
            removed += 1
        return removed

    def _clip_oversized_groups(self, groups):
        clipped = 0
        history_budget = self._budget("history")
        per_msg_budget = max(600, int(history_budget * 0.4))
        for group in groups:
            if _char_len(group) <= per_msg_budget * max(1, len(group)):
                continue
            clipped += self._clip_group(group, per_msg_budget)
        return clipped

    def _clip_protected(self, group):
        protected_budget = self._budget("protected")
        if _char_len(group) <= protected_budget:
            return 0
        per_msg_budget = max(1200, protected_budget // max(1, len(group)))
        return self._clip_group(group, per_msg_budget)

    @staticmethod
    def _clip_group(group, per_msg_budget):
        clipped = 0
        for msg in group:
            content = msg.get("content")
            if isinstance(content, str) and len(content) > per_msg_budget:
                msg["content"] = _tail_clip(content, per_msg_budget)
                clipped += 1
        return clipped


def trim_messages_with_metadata(messages, **kwargs):
    return ContextBudgeter(**kwargs).trim(messages)


def trim_messages(messages):
    trimmed, _ = trim_messages_with_metadata(messages)
    return trimmed


def measure_messages(messages):
    _, metrics = trim_messages_with_metadata(messages)
    return metrics
