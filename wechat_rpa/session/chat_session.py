#!/usr/bin/env python3
"""L4 Chat Session - 会话状态管理 + 去重核心.

去重策略：
- 相似度去重：OCR 非确定性导致文本微小差异时，用 LCS 相似度 >= 80% 匹配
"""

from typing import List, Tuple

from wechat_rpa.models.base import ChatMessage

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
    ):
        self.chat_id = chat_id
        self.chat_name = chat_name

        # 已见过消息的去重缓存：存储 (chat_name, sender, normalized_text)
        # 使用列表而非 set，因为需要支持相似度匹配
        self.seen_messages: List[Tuple[str, str, str]] = []
        self._seen_maxlen = 200

        self.last_reply_time = None
        self.reply_count = 0

    def _message_fingerprint(self, msg: ChatMessage) -> str:
        """生成消息的去重指纹。

        文字消息：用 text 内容。
        图片/表情/混合消息：用 message_type + image_description 组合，避免
        不同图片因 text 都为空而被误判为相同。
        """
        if msg.message_type in ("image", "sticker", "mixed"):
            return f"[{msg.message_type}]{msg.image_description}"
        return msg.text

    def _find_similar_seen(self, msg: ChatMessage) -> bool:
        """检查 msg 是否与历史消息相似（LCS >= 80%）。"""
        norm = _normalize_for_compare(self._message_fingerprint(msg))
        for chat, sender, hist_norm in self.seen_messages:
            if chat == msg.chat_name and sender == msg.sender:
                sim = _text_similarity(norm, hist_norm)
                if sim >= _SIMILARITY_THRESHOLD:
                    return True
        return False

    def _add_seen(self, msg: ChatMessage) -> None:
        """将消息加入 seen_messages，保持 maxlen。"""
        self.seen_messages.append(
            (msg.chat_name, msg.sender, _normalize_for_compare(self._message_fingerprint(msg)))
        )
        if len(self.seen_messages) > self._seen_maxlen:
            self.seen_messages = self.seen_messages[-self._seen_maxlen:]

    def filter_new(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        if not messages:
            return []

        new_messages = []
        for msg in messages:
            # 相似度去重：与历史消息做 LCS >= 阈值匹配
            if self._find_similar_seen(msg):
                continue
            new_messages.append(msg)

        # 将本轮所有消息记录到 seen_messages（标记为已读）
        for msg in messages:
            self._add_seen(msg)

        return new_messages

    def record_sent(self, text: str) -> None:
        """记录 Bot 自己发送的消息。"""
        import time
        self.last_reply_time = time.time()
        self.reply_count += 1

    def to_dict(self) -> dict:
        """序列化会话状态，用于持久化。"""
        return {
            "chat_id": self.chat_id,
            "chat_name": self.chat_name,
            "seen_messages": list(self.seen_messages),
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
        session.last_reply_time = data.get("last_reply_time")
        session.reply_count = data.get("reply_count", 0)
        return session
