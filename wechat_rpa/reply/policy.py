#!/usr/bin/env python3
"""L4 Reply Policy - 回复决策."""

from wechat_rpa.models.base import ChatMessage, SenderType
from wechat_rpa.session.chat_session import ChatSession


class ReplyPolicy:
    def __init__(self, require_at_in_group: bool = False):
        """
        require_at_in_group: 群聊中是否必须被 @ 才回复。
                           默认 False，允许直接回复所有群聊消息。
        """
        self.require_at_in_group = require_at_in_group

    def should_reply(self, msg: ChatMessage, session: ChatSession) -> bool:
        """
        决策逻辑：
        1. 自己消息 → False
        2. 系统消息 → False
        3. 冷却期内同一聊天 → False
        4. 群聊且未@我 → False（仅在 require_at_in_group=True 时生效）
        5. 其他 → True
        """
        if msg.sender_type == SenderType.SELF:
            return False
        if msg.sender_type == SenderType.SYSTEM:
            return False
        if session.is_in_cooldown():
            return False
        if self.require_at_in_group and self._is_group_chat(msg.chat_name) and not msg.is_at_me:
            return False
        return True

    def _is_group_chat(self, chat_name: str) -> bool:
        """通过聊天名称启发式判断是否为群聊."""
        return (
            ("(" in chat_name and ")" in chat_name)
            or ("（" in chat_name and "）" in chat_name)
            or chat_name.endswith("群")
            or "群聊" in chat_name
        )
