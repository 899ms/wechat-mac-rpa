#!/usr/bin/env python3
"""L4 Reply Generator - 回复内容生成."""

from wechat_rpa.models.base import ChatMessage
from wechat_rpa.session.chat_session import ChatSession


class ReplyGenerator:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def generate(self, msg: ChatMessage, session: ChatSession) -> str:
        """
        生成回复内容。

        - 若 llm_client 为 None，返回基于消息内容的兜底短回复。
        - 系统提示词约束：友好自然、简洁（≤50字）、群聊@时直接回答。
        - 生成失败时返回兜底文案 "收到"。
        """
        if self.llm_client is None:
            return self._fallback_reply(msg)

        try:
            raw = self.llm_client.chat(
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": f"聊天：{msg.chat_name}\n消息：{msg.text}"},
                ]
            )
            return self._clean_reply(raw)
        except Exception:
            return "收到"

    def _system_prompt(self) -> str:
        return (
            "你是一个微信聊天助手。规则：\n"
            "1. 只输出你要发送的回复内容，绝对不要输出思考过程\n"
            "2. 回复简洁自然，不超过50字\n"
            "3. 群聊中被@时直接回答问题\n"
            "4. 禁止以'等等'、'用户可能'、'我应该'、'让我想想'、'思考一下'等开头\n"
            "5. 直接给出回答，不要解释你在做什么"
        )

    def _clean_reply(self, text: str) -> str:
        """不再做思考内容过滤。若 LLM 输出思考过程，问题应在 prompt/LLM 层解决。"""
        text = text.strip()
        if not text:
            return "收到"
        return text

    def _fallback_reply(self, msg: ChatMessage) -> str:
        text = msg.text.lower()
        if msg.is_at_me:
            return "收到"
        if any(k in text for k in ("?", "？", "吗", "呢", "什么", "怎么", "为什么", "多少")):
            return "收到，稍后回复你"
        return "收到"
