#!/usr/bin/env python3
"""L4 Reply Generator - 回复内容生成."""

from typing import List

from wechat_rpa.models.base import ChatMessage, SenderType
from wechat_rpa.session.chat_session import ChatSession
from wechat_rpa.tools import get_registry, register_builtin_tools


class ReplyGenerator:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        # 最后一次调用的 prompt/response（供 debug 使用）
        self.last_system_prompt: str = ""
        self.last_user_prompt: str = ""
        self.last_raw_response: str = ""
        # 注册内置工具
        self.tool_registry = get_registry()
        register_builtin_tools()

    def generate(self, unreplied: List[ChatMessage], all_messages: List[ChatMessage]) -> List[str]:
        """
        生成回复内容，返回多条回复列表（最多3条）。
        每条对应一条未读消息的回复，'跳过'表示不回复。

        Args:
            unreplied: 所有未读消息列表（按时间顺序）
            all_messages: 当前聊天的完整消息历史（按时间顺序），作为上下文

        Returns:
            非空的回复文本列表
        """
        if not unreplied:
            return []

        fallback_msg = unreplied[-1]

        if self.llm_client is None:
            return [self._fallback_reply(fallback_msg)]

        system_prompt = self._system_prompt()
        user_prompt = self._build_user_prompt(unreplied, all_messages)
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        tools = self.tool_registry.to_openai_schemas()

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                raw = self.llm_client.chat(messages=messages, tools=tools if tools else None)

                # 工具调用处理
                if hasattr(raw, "tool_calls") and raw.tool_calls:
                    assistant_msg = {
                        "role": "assistant",
                        "content": raw.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in raw.tool_calls
                        ],
                    }
                    messages.append(assistant_msg)

                    for tc in raw.tool_calls:
                        tool_name = tc.function.name
                        tool_args = tc.function.arguments
                        if self.tool_registry.has(tool_name):
                            result = self.tool_registry.get(tool_name).execute(tool_args)
                        else:
                            result = f"工具 {tool_name} 不存在"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                    raw2 = self.llm_client.chat(messages=messages, tools=tools if tools else None)
                    text = raw2 if isinstance(raw2, str) else getattr(raw2, "content", str(raw2))
                    self.last_raw_response = text
                    replies = self._parse_replies(text)
                    if replies:
                        return replies
                    continue

                # 普通文本回复
                text = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
                self.last_raw_response = text
                replies = self._parse_replies(text)
                if replies:
                    return replies
                self.last_raw_response = f"[空回复，第{attempt+1}次]"

            except Exception as e:
                self.last_raw_response = f"[ERROR 第{attempt+1}次: {type(e).__name__}: {e}]"
                if attempt < max_retries:
                    import time
                    time.sleep(1)

        return [self._fallback_reply(fallback_msg)]

    def _parse_replies(self, text: str) -> List[str]:
        """解析 AI 的 JSON 回复，提取 replies 数组。最多3条。"""
        import json
        import re

        text = text.strip()
        if not text:
            return []

        # 尝试提取 JSON（可能混在 markdown 代码块中）
        # 先找 ```json ... ```
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            # 找最外层的大括号
            m = re.search(r"(\{.*\})", text, re.DOTALL)
            if m:
                text = m.group(1)

        try:
            data = json.loads(text)
            replies = data.get("replies", [])
            if not isinstance(replies, list):
                replies = []
            # 过滤空字符串和敷衍词
            filtered = []
            for r in replies:
                r = str(r).strip()
                if not r or r in ("收到", "好的", "嗯", "OK", "1"):
                    continue
                filtered.append(r)
            return filtered[:3]
        except (json.JSONDecodeError, Exception):
            # JSON 解析失败，回退：把整段文本当作单条回复
            if text and text not in ("收到", "好的", "嗯", "OK", "1"):
                return [text]
            return []

    def _system_prompt(self) -> str:
        return (
            "你没有固定人设。回复时请参照**对方**（不是你自己）的说话风格，"
            "自然地融入对话。\n\n"
            "风格参照：\n"
            "- 看对方怎么说话，你就怎么回\n"
            "- 对方风趣你就俏皮，对方正经你就礼貌\n"
            "- 不要刻意用技术术语或互联网黑话\n"
            "- **不要重复自己之前说过的梗或内容**，每次回复都是新的\n"
            "- 自然融入诗句、名言、歌词、俗语，增加文化感\n"
            "- 适当穿插英语、日语、法语等小语种，形成混搭效果\n"
            "- 语气略带傲娇或云淡风轻，装逼但不油腻\n\n"
            "输出格式（严格遵循）：\n"
            "必须输出 JSON，格式如下（不要加 markdown 代码块）：\n"
            '{"replies": ["回复内容1", "回复内容2"]}\n'
            "- replies 数组包含 0-3 条回复\n"
            "- 不需要回复时 replies 为空数组 []\n"
            "- 可以对单条消息分多条回复\n"
            "- 也可以对多条消息合并回复\n"
            "- 绝对不要输出思考过程或解释\n\n"
            "规则：\n"
            "1. 只输出 JSON，绝对不要输出其他内容\n"
            "2. 每条回复简洁自然，不超过50字\n"
            "3. 群聊中被@时直接回答问题\n"
            "4. 禁止以'等等'、'用户可能'、'我应该'等开头\n"
            "5. 【绝对禁止】回复「收到」「好的」「嗯」「OK」「1」等敷衍性词语\n"
            "6. 参照对方的语气和风格来回复，不要延续你自己的风格\n"
            "7. 引用和外语要自然融入，不要强行堆砌\n"
            "8. 如果群里的人在排队接龙，你可以自然地加入他们"
        )

    def _build_user_prompt(self, unreplied: List[ChatMessage], all_messages: List[ChatMessage]) -> str:
        """构建包含完整上下文的 user prompt，给未读消息标序号。"""
        chat_name = unreplied[-1].chat_name if unreplied else ""
        lines = [f"聊天名称：{chat_name}", ""]

        if all_messages:
            lines.append("【消息上下文】")
            self_messages = [m for m in all_messages if m.sender_type == SenderType.SELF]
            kept_self = self_messages[-3:] if len(self_messages) > 3 else self_messages
            skipped_self_count = len(self_messages) - len(kept_self)

            for m in all_messages:
                sender_name = "我" if m.sender_type == SenderType.SELF else m.sender
                status = "【未读】" if not m.replied and m.sender_type != SenderType.SELF else ""
                if m.sender_type == SenderType.SELF and m not in kept_self:
                    continue
                lines.append(f"{sender_name}：{m.text}{status}")

            if skipped_self_count > 0:
                lines.append(f"（... 省略了之前自己发的 {skipped_self_count} 条消息 ...）")
            lines.append("")

        lines.append("【未读消息】")
        for i, m in enumerate(unreplied, 1):
            sender_name = "我" if m.sender_type == SenderType.SELF else m.sender
            lines.append(f"[{i}] {sender_name}：{m.text}")
        lines.append("")
        lines.append("请根据上下文，决定生成几条回复（0-3条），输出 JSON。")
        lines.append("可以对单条消息分多条回复，也可以合并回复，不需要时 replies 为空。")

        return "\n".join(lines)

    def _clean_reply(self, text: str) -> str:
        """不再做思考内容过滤。若 LLM 输出思考过程，问题应在 prompt/LLM 层解决。"""
        text = text.strip()
        # 如果 LLM 返回空或只包含被禁止的敷衍词，视为无效回复
        if not text or text in ("收到", "好的", "嗯", "OK", "1"):
            return ""
        return text

    def _fallback_reply(self, msg: ChatMessage) -> str:
        """兜底回复：基于消息内容给出自然回应，绝不说"收到"。"""
        text = msg.text.lower()
        # 被@时
        if msg.is_at_me:
            return "刚网卡了一下，你再说一遍？"
        # 疑问句
        if any(k in text for k in ("?", "？", "吗", "呢", "什么", "怎么", "为什么", "多少")):
            return "这个问题有意思，我得想想再回你"
        # 打招呼
        if any(k in text for k in ("在吗", "在？", "你好", "hi", "hello")):
            return "在呢，刚忙着没看手机"
        # 默认兜底
        return "稍等，我刚没注意看手机"
