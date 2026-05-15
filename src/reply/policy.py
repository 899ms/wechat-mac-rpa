#!/usr/bin/env python3
"""L4 Reply Policy - 回复决策."""

from src.models.base import ChatMessage, SenderType
from typing import Any


import re


def _is_group_chat(chat_name: str) -> bool:
    """通过聊天名称判断是否为群聊.
    
    群聊名以 群人数 结尾，如 'ai开发小分队（128）' 或 'xxx (5)'。
    括号前的部分才是稳定的群聊标识，括号内的数字可能变化。
    """
    return bool(re.search(r'[（(]\d+[）)]$', chat_name))


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
