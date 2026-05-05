#!/usr/bin/env python3
"""全局消息存储 - 管理所有聊天的消息历史和回复状态."""

import difflib
import hashlib
import json
import logging
import os
import re
import threading
import time
import traceback
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


def _normalize_text(text: str) -> str:
    """文本归一化：压缩连续空白为单个空格，去除首尾空白。"""
    return " ".join(text.split())


def _jaccard_2gram(a: str, b: str) -> float:
    """计算两个字符串的 2-gram Jaccard 相似度。"""
    if not a or not b:
        return 0.0
    ga = set(a[i:i + 2] for i in range(len(a) - 1))
    gb = set(b[i:i + 2] for i in range(len(b) - 1))
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


def _is_group_chat_name(chat_name: str) -> bool:
    """判断聊天名称是否为群聊（以 群人数 结尾，如 'ai开发小分队（128）'）。"""
    return bool(re.search(r'（\d+）$', chat_name))


def _normalize_sender(chat_name: str, msg: ChatMessage) -> str:
    """标准化 sender 用于去重匹配。

    规则：
    - 自己发的消息 → "自己"
    - 私聊对方：sender 是"对方"/空/"[未知]" → 用 chat_name（对方昵称）替代
    - 群聊对方：保留原始 sender（具体昵称或"对方"）
    """
    if msg.sender_type == SenderType.SELF:
        return "自己"
    if not _is_group_chat_name(chat_name):
        # 私聊：对方 sender 统一为 chat_name，避免 API 昵称识别不稳定导致去重失效
        return chat_name
    # 群聊：保留原始 sender（具体昵称或"对方"）
    return msg.sender


def _msg_id(chat_name: str, msg: ChatMessage) -> str:
    """消息唯一ID：用 chat_name + 标准化 sender + 内容指纹。

    文字消息：基于 text。
    图片/表情/混合消息：基于 message_type + image_description，避免不同图片
    因 text 都为空而被误判为相同。
    """
    if msg.message_type in ("image", "sticker", "mixed"):
        content = f"[{msg.message_type}]{msg.image_description}"
    else:
        content = msg.text
    normalized = _normalize_text(content)
    text_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]
    normalized_sender = _normalize_sender(chat_name, msg)
    return f"{chat_name}|{normalized_sender}|{text_hash}"


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
            sim = _jaccard_2gram(desc, hist_desc)
            if sim >= 0.08:
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

    normalized = _normalize_text(text)
    for hist_msg in state.messages[-lookback:]:
        # 跳过 Bot 自己的消息，避免拿 Bot 回复去重用户新消息
        if hist_msg.sender_type.value == "self":
            continue
        # 跳过图片类消息（不参与文字模糊去重）
        if hist_msg.message_type in ("image", "sticker", "mixed"):
            continue
        other = _normalize_text(hist_msg.text)
        if not other:
            continue
        similarity = difflib.SequenceMatcher(None, normalized, other).ratio()
        if similarity >= threshold:
            return True
    return False


def _match_single(a: ChatMessage, b: ChatMessage, chat_name: str) -> bool:
    """直接比较两条消息是否匹配（用于对齐）。

    文字：SequenceMatcher >= 0.80
    图片：2-gram Jaccard >= 0.001（容错极大，应对 qwen 描述不稳定）
    """
    # 精确匹配（使用标准化 sender）
    if _msg_id(chat_name, a) == _msg_id(chat_name, b):
        return True
    # sender_type 不同直接不匹配（避免自己消息和对方消息误匹配）
    if a.sender_type != b.sender_type:
        return False
    # 类型不同直接不匹配
    if a.message_type != b.message_type:
        return False
    # 文字消息
    if a.message_type == "text":
        text_a = _normalize_text(a.text)
        text_b = _normalize_text(b.text)
        if not text_a or not text_b:
            return False
        return difflib.SequenceMatcher(None, text_a, text_b).ratio() >= 0.80
    # 图片/表情/混合：极低阈值 Jaccard
    desc_a = a.image_description
    desc_b = b.image_description
    if not desc_a or not desc_b:
        return False
    sim = _jaccard_2gram(desc_a, desc_b)
    return sim >= 0.08


def _lcs_match(history: List[ChatMessage], tick: List[ChatMessage], chat_name: str) -> set:
    """LCS 序列对齐：返回 tick 中匹配 history 的索引集合。

    使用二值 match_score：_match_single 返回 True → 得 1 分，否则 0 分。
    回溯得到 matched_tick_indices，用于判断 tick 中哪些消息是旧的。
    """
    m, n = len(history), len(tick)
    if m == 0 or n == 0:
        return set()

    # dp[i][j] = history[0:i] 和 tick[0:j] 的 LCS 长度
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if _match_single(history[i - 1], tick[j - 1], chat_name):
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # 回溯找匹配的 tick 索引
    matched = set()
    i, j = m, n
    while i > 0 and j > 0:
        if _match_single(history[i - 1], tick[j - 1], chat_name):
            # match 时 dp[i][j] 一定等于 dp[i-1][j-1]+1（单调性保证）
            matched.add(j - 1)
            i -= 1
            j -= 1
        elif dp[i][j] == dp[i - 1][j]:
            i -= 1
        else:
            j -= 1

    return matched


class GlobalStore:
    """全局存储：管理所有聊天的状态，统一去重、持久化."""

    def __init__(self, max_messages: int = 200, state_file: str = "data/global_state.json"):
        self.chats: Dict[str, ChatState] = {}
        self.max_messages = max_messages
        self._state_file = Path(state_file)
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._screenshots_dir = self._state_file.parent / "screenshots"
        self._screenshots_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._load()

    def _merge_tick_legacy(self, chat_name: str, messages: List[ChatMessage]) -> List[ChatMessage]:
        """旧算法：滑动前缀匹配（保留用于 A/B 对比测试）。"""
        state = self.chats[chat_name]

        def _in_history(msg: ChatMessage) -> bool:
            return _msg_id(chat_name, msg) in state._msg_ids or _is_fuzzy_duplicate(
                state, msg, lookback=len(state.messages)
            )

        # tick 内去重
        seen_ids = set()
        unique_messages = []
        for msg in messages:
            mid = _msg_id(chat_name, msg)
            if mid not in seen_ids:
                seen_ids.add(mid)
                unique_messages.append(msg)
        messages = unique_messages

        if not messages or not state.messages:
            return messages if not state.messages else []

        search_window = min(len(state.messages), max(50, len(messages) * 3))
        history_window = state.messages[-search_window:]

        best_match_len = 0
        best_match_start = -1
        for i in range(len(history_window)):
            match_len = 0
            for j in range(len(messages)):
                if i + j >= len(history_window):
                    break
                if _match_single(history_window[i + j], messages[j], chat_name):
                    match_len += 1
                else:
                    break
            if match_len > best_match_len:
                best_match_len = match_len
                best_match_start = i

        if best_match_len == len(messages):
            return []
        elif best_match_len >= 1:
            match_end_in_history = best_match_start + best_match_len
            if match_end_in_history >= len(history_window) - 2:
                return messages[best_match_len:]
            else:
                return [msg for msg in messages if not _in_history(msg)]
        else:
            return [msg for msg in messages if not _in_history(msg)]

    def _merge_tick_lcs(self, chat_name: str, messages: List[ChatMessage]) -> List[ChatMessage]:
        """新算法：LCS 序列对齐（独立出来用于 A/B 对比测试）。"""
        state = self.chats[chat_name]

        def _in_history(msg: ChatMessage) -> bool:
            return _msg_id(chat_name, msg) in state._msg_ids or _is_fuzzy_duplicate(
                state, msg, lookback=len(state.messages)
            )

        # tick 内去重
        seen_ids = set()
        unique_messages = []
        for msg in messages:
            mid = _msg_id(chat_name, msg)
            if mid not in seen_ids:
                seen_ids.add(mid)
                unique_messages.append(msg)
        messages = unique_messages

        if not messages or not state.messages:
            return messages if not state.messages else []

        search_window = min(len(state.messages), 50)
        history_window = state.messages[-search_window:]
        matched = _lcs_match(history_window, messages, chat_name)

        if not matched:
            return [msg for msg in messages if not _in_history(msg)]

        max_matched = max(matched)
        return [
            messages[i]
            for i in range(len(messages))
            if i not in matched and i > max_matched
        ]

    def merge_tick(self, chat_name: str, messages: List[ChatMessage]) -> Tuple[ChatState, List[ChatMessage]]:
        """
        合并 tick 检测到的消息，返回 (state, 未回复的消息列表).

        当前使用旧算法（滑动前缀匹配）。LCS 新算法在 _merge_tick_lcs 中，
        待 A/B 测试通过后再切换。
        """
        if chat_name not in self.chats:
            self.chats[chat_name] = ChatState(
                chat_id=f"chat_{len(self.chats)}",
                chat_name=chat_name,
            )

        state = self.chats[chat_name]
        new_messages = self._merge_tick_lcs(chat_name, messages)

        # 添加新消息到历史
        for msg in new_messages:
            msg.chat_name = chat_name
            state.messages.append(msg)
            state._msg_ids.add(_msg_id(chat_name, msg))

        # 裁剪旧消息
        if len(state.messages) > self.max_messages:
            removed = state.messages[:-self.max_messages]
            state.messages = state.messages[-self.max_messages:]
            for msg in removed:
                state._msg_ids.discard(_msg_id(chat_name, msg))

        # 收集所有未回复的消息（按时间顺序）
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
                        message_type=m.get("message_type", "text"),
                        image_description=m.get("image_description", ""),
                        image_text=m.get("image_text", ""),
                        is_image_duplicate=m.get("is_image_duplicate", False),
                    )
                    state.messages.append(msg)
                    state._msg_ids.add(_msg_id(chat_name, msg))
                self.chats[chat_name] = state
        except (json.JSONDecodeError, FileNotFoundError, PermissionError, OSError) as e:
            _logger.warning(f"加载状态失败: {type(e).__name__}: {e}")
        except Exception as e:
            _logger.error(f"加载状态发生未预期错误: {type(e).__name__}: {e}\n{traceback.format_exc()}")

    def save(self):
        """保存状态到磁盘（加锁保护读-改-写操作）"""
        with self._lock:
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
                            }
                            for m in state.messages
                        ],
                    }
                tmp_file = self._state_file.with_suffix(".tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_file, self._state_file)
            except (PermissionError, OSError) as e:
                _logger.warning(f"GlobalStore save failed (IO): {type(e).__name__}: {e}")
            except Exception as e:
                _logger.error(f"GlobalStore save failed unexpectedly: {type(e).__name__}: {e}\n{traceback.format_exc()}")

    def save_screenshot(self, image_path: str, session_id: str = None) -> str:
        """保存截图到 data/screenshots/ 目录。"""
        import shutil
        from datetime import datetime
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"wechat_{session_id}_{timestamp}.png"
        filepath = self._screenshots_dir / filename
        shutil.copy2(image_path, filepath)
        return str(filepath)
