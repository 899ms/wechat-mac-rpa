#!/usr/bin/env python3
"""全局消息存储 - 管理所有聊天的消息历史和回复状态."""

import difflib
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from wechat_rpa.models.base import ChatMessage, SenderType

_logger = logging.getLogger("wechat_rpa.global_store")


@dataclass
class ChatState:
    """单个聊天的完整状态（消息历史 + 会话状态）"""
    chat_id: str
    chat_name: str
    messages: List[ChatMessage] = field(default_factory=list)
    _msg_ids: set = field(default_factory=set)  # 去重集合（不序列化）


def _text_hash(text: str) -> str:
    """文本归一化后计算 hash"""
    normalized = " ".join(text.split())
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def _msg_id(chat_name: str, msg: ChatMessage) -> str:
    """消息唯一ID：用 chat_name + sender + 内容指纹。

    文字消息：基于 text。
    图片/表情/混合消息：基于 message_type + image_description，避免不同图片
    因 text 都为空而被误判为相同。
    """
    if msg.message_type in ("image", "sticker", "mixed"):
        content = f"[{msg.message_type}]{msg.image_description}"
    else:
        content = msg.text
    normalized = " ".join(content.split())
    text_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]
    return f"{chat_name}|{msg.sender}|{text_hash}"


def _is_fuzzy_duplicate(state, msg: ChatMessage, lookback: int = 10) -> bool:
    """模糊去重：对最近 lookback 条消息做文本相似度比较。

    OCR 偶尔错几个字，精确 hash 会失效。用 difflib.SequenceMatcher
    计算相似度，>= threshold 视为同一条消息。

    图片/表情/混合消息：基于 image_description 做 2-gram Jaccard 模糊去重。

    阈值按消息长度动态调整：越短的消息要求越严格（避免不同短句误判）。
    只对 lookback 条消息比较，避免遍历全部历史影响性能。
    """
    # 图片/表情/混合消息：基于 image_description 做 2-gram Jaccard
    if msg.message_type in ("image", "sticker", "mixed"):
        desc = msg.image_description
        if not desc:
            return False
        for hist_msg in state.messages[-lookback:]:
            if hist_msg.sender_type.value == "self":
                continue
            if hist_msg.message_type not in ("image", "sticker", "mixed"):
                continue
            hist_desc = hist_msg.image_description
            if not hist_desc:
                continue
            ba = set(desc[i:i + 2] for i in range(len(desc) - 1))
            bb = set(hist_desc[i:i + 2] for i in range(len(hist_desc) - 1))
            inter = len(ba & bb)
            union = len(ba | bb)
            sim = inter / union if union else 0.0
            if sim >= 0.2:
                return True
        return False

    text = msg.text
    if not text:
        return False

    # 按长度动态调整阈值（OCR 对中文短句容易错 1-2 个字，适当放宽）
    text_len = len(text)
    if text_len <= 3:
        threshold = 0.90
    elif text_len <= 8:
        threshold = 0.85
    elif text_len <= 20:
        threshold = 0.82
    else:
        threshold = 0.80

    normalized = " ".join(text.split())
    for hist_msg in state.messages[-lookback:]:
        # 跳过 Bot 自己的消息，避免拿 Bot 回复去重用户新消息
        if hist_msg.sender_type.value == "self":
            continue
        # 跳过图片类消息（不参与文字模糊去重）
        if hist_msg.message_type in ("image", "sticker", "mixed"):
            continue
        other = " ".join(hist_msg.text.split())
        if not other:
            continue
        similarity = difflib.SequenceMatcher(None, normalized, other).ratio()
        if similarity >= threshold:
            return True
    return False


class GlobalStore:
    """全局存储：管理所有聊天的状态，统一去重、持久化."""

    def __init__(self, max_messages: int = 200, state_file: str = "data/global_state.json"):
        self.chats: Dict[str, ChatState] = {}
        self.max_messages = max_messages
        self._state_file = Path(state_file)
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def merge_tick(self, chat_name: str, messages: List[ChatMessage]) -> Tuple[ChatState, List[ChatMessage]]:
        """
        合并 tick 检测到的消息，返回 (state, 未回复的消息列表).
        
        未回复消息包括：
        - 本次 tick 新检测到的未回复消息
        - 之前 tick 检测到但还没回复的遗留消息
        """
        if chat_name not in self.chats:
            self.chats[chat_name] = ChatState(
                chat_id=f"chat_{len(self.chats)}",
                chat_name=chat_name,
            )

        state = self.chats[chat_name]

        def _in_history(msg):
            return _msg_id(chat_name, msg) in state._msg_ids or _is_fuzzy_duplicate(state, msg)

        # 1. 从后往前找分界点：连续两条都在历史中，才确定后面都是旧消息
        new_start = 0
        for i in range(len(messages) - 2, -1, -1):
            if _in_history(messages[i]) and _in_history(messages[i + 1]):
                new_start = i + 2
                break

        # 2. 处理分界点之后的消息（确定是新消息）
        for msg in messages[new_start:]:
            if not _in_history(msg):
                msg.chat_name = chat_name
                state.messages.append(msg)
                state._msg_ids.add(_msg_id(chat_name, msg))

        # 3. 额外检查：分界点前面最多 5 条，防止边界漏掉新消息
        for msg in messages[max(0, new_start - 5):new_start]:
            if not _in_history(msg):
                msg.chat_name = chat_name
                state.messages.append(msg)
                state._msg_ids.add(_msg_id(chat_name, msg))

        # 2. 裁剪旧消息
        if len(state.messages) > self.max_messages:
            removed = state.messages[:-self.max_messages]
            state.messages = state.messages[-self.max_messages:]
            for msg in removed:
                state._msg_ids.discard(_msg_id(chat_name, msg))

        # 3. 收集所有未回复的消息（按时间顺序）
        unreplied = [
            msg for msg in state.messages
            if not msg.replied and msg.sender_type != SenderType.SELF
        ]

        return state, unreplied

    def mark_replied(self, chat_name: str, target_msg: ChatMessage, reply_text: str):
        """标记单条消息已回复。"""
        state = self.chats.get(chat_name)
        if not state:
            return
        now = time.time()

        # 用 is 匹配（target_msg 就是 state.messages 中的对象引用）
        # 如果 is 匹配不到，再用 text+sender 兜底
        for msg in state.messages:
            if msg is target_msg or (msg.text == target_msg.text and msg.sender == target_msg.sender):
                msg.replied = True
                msg.reply_text = reply_text
                msg.reply_time = now
                # 不 break，继续标记所有匹配的消息（OCR 不稳定可能导致同一条消息存了多份）

    def get_unreplied(self, chat_name: str) -> List[ChatMessage]:
        """获取某聊天中所有未回复的消息（按时间顺序）"""
        state = self.chats.get(chat_name)
        if not state:
            return []
        return [
            m for m in state.messages
            if not m.replied and m.sender_type != SenderType.SELF
        ]

    def last_reply_time(self, chat_name: str) -> Optional[float]:
        """最后回复时间（从消息中推导）"""
        state = self.chats.get(chat_name)
        if not state:
            return None
        replied_times = [
            m.reply_time for m in state.messages
            if m.replied and m.reply_time
        ]
        return max(replied_times) if replied_times else None

    def reply_count(self, chat_name: str) -> int:
        """回复次数（从消息中推导）"""
        state = self.chats.get(chat_name)
        if not state:
            return 0
        return sum(1 for m in state.messages if m.replied)

    def _load(self):
        """从磁盘加载状态"""
        if not self._state_file.exists():
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for chat_name, chat_data in data.items():
                state = ChatState(
                    chat_id=chat_data.get("chat_id", ""),
                    chat_name=chat_data.get("chat_name", chat_name),
                )
                for m in chat_data.get("messages", []):
                    msg = ChatMessage(
                        text=m.get("text", ""),
                        sender=m.get("sender", ""),
                        sender_type=SenderType(m.get("sender_type", "other")),
                        chat_name=m.get("chat_name", chat_name),
                        is_at_me=m.get("is_at_me", False),
                        replied=m.get("replied", False),
                        reply_text=m.get("reply_text", ""),
                        reply_time=m.get("reply_time"),
                    )
                    state.messages.append(msg)
                    state._msg_ids.add(_msg_id(chat_name, msg))
                self.chats[chat_name] = state
        except Exception as e:
            _logger.warning(f"加载状态失败: {e}")

    def save(self):
        """保存状态到磁盘"""
        try:
            data = {}
            for chat_name, state in self.chats.items():
                data[chat_name] = {
                    "chat_id": state.chat_id,
                    "chat_name": state.chat_name,
                    "messages": [
                        {
                            "text": m.text,
                            "sender": m.sender,
                            "sender_type": m.sender_type.value,
                            "chat_name": m.chat_name,
                            "is_at_me": m.is_at_me,
                            "replied": m.replied,
                            "reply_text": m.reply_text,
                            "reply_time": m.reply_time,
                            "message_type": m.message_type,
                            "image_description": m.image_description,
                            "image_text": m.image_text,
                            "is_image_duplicate": m.is_image_duplicate,
                        }
                        for m in state.messages
                    ],
                }
            tmp_file = self._state_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self._state_file)
        except Exception as e:
            _logger.warning(f"GlobalStore save failed: {e}")
