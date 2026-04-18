#!/usr/bin/env python3
"""
Mac 微信简易 RPA 机器人

基于 pyautogui + AppleScript
功能：发送消息、简单回复
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# 加载 Kimi API
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
    print("pip install openai")
    sys.exit(1)

class MacWeChatBot:
    """Mac 微信机器人"""
    
    def __init__(self):
        # 初始化 Kimi 客户端
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.kimi.com/coding/v1"),
            default_headers={
                "User-Agent": "claude-code/0.1.39",
                "X-Coding-Agent": "claude-code"
            }
        )
        self.model = os.getenv("LLM_MODEL", "kimi-for-coding")
        self.conversations = {}
    
    def activate_wechat(self):
        """激活微信窗口"""
        subprocess.run([
            'osascript', '-e', 
            'tell application "WeChat" to activate'
        ])
        time.sleep(0.5)
    
    def send_message(self, message: str) -> bool:
        """
        发送消息到当前聊天窗口
        需要微信窗口已经打开
        """
        try:
            import pyautogui
            import pyperclip
            
            # 激活微信
            self.activate_wechat()
            
            # 复制消息
            pyperclip.copy(message)
            
            # 粘贴 (Cmd+V)
            pyautogui.keyDown('command')
            pyautogui.keyDown('v')
            pyautogui.keyUp('v')
            pyautogui.keyUp('command')
            
            time.sleep(0.3)
            
            # 发送 (Return)
            pyautogui.press('return')
            
            return True
        except Exception as e:
            print(f"发送失败: {e}")
            return False
    
    def get_llm_reply(self, user_id: str, message: str) -> str:
        """获取 Kimi 回复"""
        if user_id not in self.conversations:
            self.conversations[user_id] = [
                {"role": "system", "content": "你是微信智能助手，回复简洁友好"}
            ]
        
        self.conversations[user_id].append(
            {"role": "user", "content": message}
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.conversations[user_id][-10:],  # 最近5轮
                temperature=0.7,
                max_tokens=500
            )
            reply = response.choices[0].message.content
            self.conversations[user_id].append(
                {"role": "assistant", "content": reply}
            )
            return reply
        except Exception as e:
            return f"抱歉，出错了: {e}"
    
    def run_interactive(self):
        """交互式运行"""
        print("=" * 60)
        print("🤖 Mac 微信 RPA 机器人")
        print("=" * 60)
        print("\n⚠️  使用说明:")
        print("1. 确保微信已登录并打开")
        print("2. 在微信中打开要对话的聊天窗口")
        print("3. 输入消息，机器人会自动回复")
        print("4. 输入 'exit' 退出\n")
        print("=" * 60)
        
        # 检查微信
        result = subprocess.run(
            ['pgrep', '-x', 'WeChat'],
            capture_output=True
        )
        if result.returncode != 0:
            print("❌ 微信未运行，请先启动微信")
            return
        
        print("✅ 微信已运行")
        
        user_id = "mac_user_001"
        
        while True:
            try:
                msg = input("\n💬 输入消息 (或exit退出): ").strip()
                
                if msg.lower() == 'exit':
                    break
                
                if not msg:
                    continue
                
                # 获取AI回复
                print("🤔 思考中...")
                reply = self.get_llm_reply(user_id, msg)
                
                print(f"🤖 准备发送: {reply[:50]}...")
                
                # 发送到微信
                if self.send_message(reply):
                    print("✅ 已发送到微信")
                else:
                    print("❌ 发送失败，请检查微信窗口是否打开")
                
            except KeyboardInterrupt:
                print("\n\n正在退出...")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
        
        print("\n👋 再见!")


if __name__ == "__main__":
    # 检查依赖
    try:
        import pyautogui
        import pyperclip
    except ImportError:
        print("请先安装依赖:")
        print("pip install pyautogui pyperclip openai")
        sys.exit(1)
    
    bot = MacWeChatBot()
    bot.run_interactive()
