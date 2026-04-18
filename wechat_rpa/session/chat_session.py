#!/usr/bin/env python3
"""L4 Chat Session - 会话状态管理 + 去重核心.

去重策略（三层防线）：
1. 窗口指纹：整个消息列表完全重复时快速拦截
2. 回声检测：Bot 自己刚发的消息被回显时过滤
3. 相似度去重：OCR 非确定性导致文本微小差异时，用 LCS 相似度 >= 90% 匹配
"""

import time
from collections import deque
from hashlib import md5
from typing import List, Optional, Tuple

from wechat_rpa.models.base import ChatMessage, SentMessage

# OCR 容错相似度阈值（80% 覆盖更多 OCR 变体，如空格差异、个别字错误）
_SIMILARITY_THRESHOLD = 0.80


def _normalize_for_compare(text: str) -> str:
    """去空格、去换行，用于相似度比较前的归一化。"""
    return text.replace(" ", "").replace("\n", "").replace("\t", "")


def _text_similarity(a: str, b: str) -> float:
    """LCS 最长公共子序列相似度，返回 0~1。"""
    a = _normalize_for_compare(a)
    b = _normalize_for_compare(b)
    if not a or not b:
        return 0.0
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    return 2 * lcs / (m + n)


class ChatSession:
    def __init__(
        self,
        chat_id: str,
        chat_name: str,
        echo_time_window: float = 20.0,
        echo_history_limit: int = 5,
    ):
        self.chat_id = chat_id
        self.chat_name = chat_name
        self.echo_time_window = echo_time_window
        self.echo_history_limit = echo_history_limit

        # 已见过消息的去重缓存：存储 (chat_name, sender, normalized_text)
        # 使用列表而非 set，因为需要支持相似度匹配
        self.seen_messages: List[Tuple[str, str, str]] = []
        self._seen_maxlen = 200

        # 已见过的消息窗口指纹（用于检测滚动导致的重复视图），最多保留最近 100 个
        self.seen_window_hashes: deque[str] = deque(maxlen=100)

        # 自己发送的消息记录（用于回声检测）
        self.sent_messages: List[SentMessage] = []

        self.last_reply_time: Optional[float] = None
        self.reply_count: int = 0

    def _find_similar_seen(self, msg: ChatMessage) -> bool:
        """检查 msg 是否与历史消息相似（LCS >= 90%）。"""
        norm = _normalize_for_compare(msg.text)
        for chat, sender, hist_norm in self.seen_messages:
            if chat == msg.chat_name and sender == msg.sender:
                sim = _text_similarity(norm, hist_norm)
                if sim >= _SIMILARITY_THRESHOLD:
                    return True
        return False

    def _add_seen(self, msg: ChatMessage) -> None:
        """将消息加入 seen_messages，保持 maxlen。"""
        self.seen_messages.append(
            (msg.chat_name, msg.sender, _normalize_for_compare(msg.text))
        )
        if len(self.seen_messages) > self._seen_maxlen:
            self.seen_messages = self.seen_messages[-self._seen_maxlen:]

    def filter_new(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        if not messages:
            return []

        # 1. 窗口指纹检测：如果整个消息列表近期已出现过，快速拦截
        window_hash = self._hash_messages(messages)
        if window_hash in self.seen_window_hashes:
            return []

        new_messages = []
        for i, msg in enumerate(messages):
            # 2. 回声检测：是否是自己刚发的
            recent_sent = self.sent_messages[-self.echo_history_limit:] if self.sent_messages else []
            if any(self._is_echo(msg.text, sent) for sent in reversed(recent_sent)):
                continue

            # 3. 相似度去重：与历史消息做 LCS >= 90% 匹配
            if self._find_similar_seen(msg):
                continue

            new_messages.append(msg)

        # 将本轮所有消息记录到 seen_messages
        for msg in messages:
            self._add_seen(msg)

        self.seen_window_hashes.append(window_hash)
        return new_messages

    def record_sent(self, text: str) -> None:
        """记录 Bot 自己发送的消息。"""
        self.sent_messages.append(SentMessage(text=text, sent_at=time.time()))
        self.last_reply_time = time.time()
        self.reply_count += 1

    def to_dict(self) -> dict:
        """序列化会话状态，用于持久化。"""
        return {
            "chat_id": self.chat_id,
            "chat_name": self.chat_name,
            "seen_messages": list(self.seen_messages),
            "seen_window_hashes": list(self.seen_window_hashes),
            "sent_messages": [
                {"text": s.text, "sent_at": s.sent_at}
                for s in self.sent_messages
            ],
            "last_reply_time": self.last_reply_time,
            "reply_count": self.reply_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        """从 dict 反序列化会话状态。"""
        session = cls(
            chat_id=data.get("chat_id", ""),
            chat_name=data.get("chat_name", ""),
        )
        session.seen_messages = [
            tuple(item) if isinstance(item, (list, tuple)) else item
            for item in data.get("seen_messages", [])
        ]
        session.seen_window_hashes = deque(
            data.get("seen_window_hashes", []),
            maxlen=session.seen_window_hashes.maxlen
        )
        from wechat_rpa.models.base import SentMessage
        session.sent_messages = [
            SentMessage(text=s["text"], sent_at=s["sent_at"])
            for s in data.get("sent_messages", [])
        ]
        session.last_reply_time = data.get("last_reply_time")
        session.reply_count = data.get("reply_count", 0)
        return session

    def is_in_cooldown(self, seconds: float = 60.0) -> bool:
        """检查是否在冷却期内（默认60秒，避免活跃群聊中频繁回复）"""
        if self.last_reply_time is None:
            return False
        return (time.time() - self.last_reply_time) < seconds

    def _is_echo(self, msg_text: str, sent: SentMessage) -> bool:
        """判断 msg 是否是 sent 的"回声"。条件：时间窗口内 + 文本高相似度。"""
        time_match = (time.time() - sent.sent_at) < self.echo_time_window
        # 使用 LCS 相似度，覆盖 OCR 标点差异、空格差异等情况
        text_match = _text_similarity(msg_text, sent.text) >= _SIMILARITY_THRESHOLD
        return time_match and text_match

    def _hash_messages(self, messages: List[ChatMessage]) -> str:
        """计算消息列表的上下文指纹（对 OCR 噪声鲁棒：去掉空格）。"""
        content = "|".join(
            f"{m.chat_name}:{m.sender}:{md5(_normalize_for_compare(m.text).encode()).hexdigest()}"
            for m in messages
        )
        return md5(content.encode()).hexdigest()
