#!/usr/bin/env python3
"""L4 Reply Policy - 回复决策."""

from wechat_rpa.models.base import ChatMessage, SenderType
from typing import Any


def _is_group_chat(chat_name: str) -> bool:
    """通过聊天名称启发式判断是否为群聊."""
    return (
        ("(" in chat_name and ")" in chat_name)
        or ("（" in chat_name and "）" in chat_name)
        or chat_name.endswith("群")
        or "群聊" in chat_name
    )


class ReplyPolicy:
    def __init__(self, require_at_in_group: bool = False):
        self.require_at_in_group = require_at_in_group

    def should_reply(self, msg: ChatMessage, session: Any) -> bool:
        """
        所有回复判断交给 AI 自主决定（输出 replies: [] 表示不回复）。
        代码层只做最基本的过滤。
        """
        if msg.sender_type == SenderType.SELF:
            return False
        if msg.sender_type == SenderType.SYSTEM:
            return False
        return True
