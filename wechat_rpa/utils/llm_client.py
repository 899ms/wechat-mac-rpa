"""
Kimi LLM 客户端
兼容之前的配置
"""

import os
import sys
from pathlib import Path
from typing import List, Dict

# 加载 .env
def load_env():
    env_path = Path(__file__).parent.parent.parent / "omni-bot-sdk-oss" / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value.strip('"'))

load_env()

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("pip install openai")


class KimiClient:
    """Kimi Coding Agent LLM 客户端"""
    
    def __init__(self):
        agent_name = os.getenv("CODING_AGENT_NAME", "claude-code")
        
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.kimi.com/coding/v1"),
            default_headers={
                "User-Agent": f"{agent_name}/0.1.39",
                "X-Coding-Agent": agent_name,
                "X-Client-Name": agent_name
            }
        )
        self.model = os.getenv("LLM_MODEL", "kimi-for-coding")
        self.conversations: Dict[str, List[dict]] = {}
    
    def chat(self, user_id: str, message: str, system_prompt: str = None) -> str:
        """生成回复"""
        
        if user_id not in self.conversations:
            self.conversations[user_id] = []
            if system_prompt:
                self.conversations[user_id].append(
                    {"role": "system", "content": system_prompt}
                )
        
        self.conversations[user_id].append(
            {"role": "user", "content": message}
        )
        
        # 限制历史
        if len(self.conversations[user_id]) > 21:
            self.conversations[user_id] = [
                self.conversations[user_id][0],  # system
                *self.conversations[user_id][-20:]
            ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.conversations[user_id],
                temperature=0.7,
                max_tokens=1000,
                timeout=30  # 30秒超时
            )
            
            reply = response.choices[0].message.content
            self.conversations[user_id].append(
                {"role": "assistant", "content": reply}
            )
            return reply
            
        except Exception as e:
            print(f"LLM 错误: {e}")
            return "抱歉，服务暂时不可用"
    
    def clear_history(self, user_id: str):
        if user_id in self.conversations:
            del self.conversations[user_id]


if __name__ == "__main__":
    # 测试
    client = KimiClient()
    reply = client.chat("test_user", "你好")
    print(f"回复: {reply}")
