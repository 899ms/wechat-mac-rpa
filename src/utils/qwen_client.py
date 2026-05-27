"""
Qwen LLM 客户端 - 用于回复生成
接口与 KimiClient 兼容
"""

import logging
import os
import time
from typing import List

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("pip install openai")


class QwenClient:
    """LLM API 客户端（支持 DeepSeek 官方 / DashScope 双平台）"""

    def __init__(self, model: str = "deepseek-v4-flash"):
        # 默认 DashScope（稳定有额度），如需切 DeepSeek 官方平台设 USE_DEEPSEEK_OFFICIAL=true
        use_official = os.environ.get("USE_DEEPSEEK_OFFICIAL", "").lower() in ("1", "true", "yes")
        if use_official:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            base_url = "https://api.deepseek.com/v1"
        else:
            api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
            base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY 至少设置一个")
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model
        self.is_deepseek_official = "deepseek.com" in base_url

    def chat(self, messages=None, user_id=None, message=None, system_prompt=None, tools=None, temperature=None, max_tokens=None, timeout=None, response_format=None) -> str:
        """生成回复，支持 tools（function calling）

        支持两种调用方式：
        1. 新接口: chat(messages=[...], tools=[...], temperature=0.3, max_tokens=2000)
        2. 旧接口: chat(user_id="xxx", message="...", system_prompt="...")
        """
        if messages is not None:
            return self._chat_with_messages(messages, tools=tools, temperature=temperature, max_tokens=max_tokens, timeout=timeout, response_format=response_format)
        return self._chat_with_user_id(user_id, message, system_prompt)

    def _chat_with_messages(self, messages: List[dict], tools=None, temperature=None, max_tokens=None, timeout=None, response_format=None) -> str:
        """直接透传 messages 列表调用大模型，支持 tools 和自定义参数"""
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature if temperature is not None else 0.7,
                "max_tokens": max_tokens if max_tokens is not None else 1000,
                "timeout": timeout if timeout is not None else 500,
            }
            if tools:
                kwargs["tools"] = tools
            if response_format:
                kwargs["response_format"] = response_format
            # DeepSeek 官方平台：wiki 生成开启 thinking 以提升提取能力
            if self.is_deepseek_official:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            _logger = logging.getLogger("src.llm.qwen")
            _logger.info("[Qwen] request start: model=%s tools=%s timeout=%s",
                         kwargs.get("model"), bool(kwargs.get("tools")), kwargs.get("timeout"))
            t_req_start = time.time()
            response = self.client.chat.completions.create(**kwargs)
            t_req_ms = (time.time() - t_req_start) * 1000
            _logger.info("[Qwen] request end: duration=%.0fms model=%s",
                         t_req_ms, kwargs.get("model"))
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
