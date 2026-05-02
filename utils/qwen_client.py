"""
Qwen LLM 客户端 - 用于回复生成
接口与 KimiClient 兼容
"""

import os
from typing import List

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("pip install openai")


class QwenClient:
    """Qwen API 客户端（文本聊天）"""

    def __init__(self, model: str = "deepseek-v4-flash"):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY not set")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = model

    def chat(self, messages=None, user_id=None, message=None, system_prompt=None, tools=None) -> str:
        """生成回复，支持 tools（function calling）

        支持两种调用方式：
        1. 新接口: chat(messages=[...], tools=[...])
        2. 旧接口: chat(user_id="xxx", message="...", system_prompt="...")
        """
        if messages is not None:
            return self._chat_with_messages(messages, tools=tools)
        return self._chat_with_user_id(user_id, message, system_prompt)

    def _chat_with_messages(self, messages: List[dict], tools=None) -> str:
        """直接透传 messages 列表调用大模型，支持 tools"""
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000,
                "timeout": 30,
            }
            if tools:
                kwargs["tools"] = tools
            response = self.client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            # 如果模型返回 tool_calls，也返回（让上层处理）
            if getattr(msg, "tool_calls", None):
                return msg
            return msg.content or ""
        except Exception as e:
            print(f"Qwen LLM 错误: {e}")
            return ""

    def _chat_with_user_id(self, user_id: str, message: str, system_prompt: str = None) -> str:
        """简单封装"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        return self._chat_with_messages(messages)
