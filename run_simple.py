#!/usr/bin/env python3
"""
Mac 微信 RPA 简化版
使用 AppleScript 发送消息（无需 pyautogui）
"""

import os
import sys
import subprocess
import time
from pathlib import Path

# 加载 Kimi API
env_path = Path(__file__).parent.parent / "omni-bot-sdk-oss" / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value.strip('"'))

try:
    from openai import OpenAI
except ImportError:
    print("❌ pip install openai")
    sys.exit(1)


class SimpleMacBot:
    """简化版 Mac 微信机器人"""
    
    def __init__(self):
        # Kimi 客户端
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
        self.stats = {"received": 0, "sent": 0}
    
    def get_reply(self, user_id: str, message: str) -> str:
        """获取 Kimi 回复"""
        if user_id not in self.conversations:
            self.conversations[user_id] = [
                {"role": "system", "content": "你是微信智能助手，回复简洁友好"}
            ]
        
        self.conversations[user_id].append({"role": "user", "content": message})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.conversations[user_id][-10:],
                temperature=0.7,
                max_tokens=1000
            )
            reply = response.choices[0].message.content
            self.conversations[user_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            return f"出错了: {e}"
    
    def send_to_wechat(self, message: str) -> bool:
        """
        使用 AppleScript 发送消息到微信
        
        注意：需要先在微信中打开聊天窗口
        """
        try:
            # 激活微信
            subprocess.run([
                'osascript', '-e',
                'tell application "WeChat" to activate'
            ])
            time.sleep(0.3)
            
            # 使用 AppleScript 输入消息
            # 注意：直接 keystroke 中文可能有问题，这里用粘贴板
            script = f'''
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                    delay 0.2
                    keystroke "v" using command down
                    delay 0.2
                    keystroke return
                end tell
            end tell
            '''
            
            # 复制消息到粘贴板
            subprocess.run(['pbcopy'], input=message.encode('utf-8'))
            time.sleep(0.1)
            
            # 执行 AppleScript
            subprocess.run(['osascript', '-e', script])
            return True
            
        except Exception as e:
            print(f"发送失败: {e}")
            return False
    
    def run(self):
        """运行"""
        print("=" * 60)
        print("🤖 Mac 微信 RPA 简化版")
        print("=" * 60)
        print("\n💡 使用说明:")
        print("1. 确保微信已登录")
        print("2. 在微信中打开要发送的聊天窗口")
        print("3. 输入消息，格式: 用户ID|消息内容")
        print("   示例: 文件传输助手|你好")
        print("4. 输入 'exit' 退出\n")
        print("=" * 60)
        
        while True:
            try:
                line = input("\n💬 ").strip()
                if line.lower() == 'exit':
                    break
                
                if '|' not in line:
                    print("❌ 格式错误，使用: 用户ID|消息内容")
                    continue
                
                user_id, message = line.split('|', 1)
                user_id = user_id.strip()
                message = message.strip()
                
                print(f"\n📨 收到 [{user_id}]: {message}")
                self.stats["received"] += 1
                
                # 获取回复
                print("🤔 生成回复...")
                reply = self.get_reply(user_id, message)
                print(f"🤖 回复: {reply[:100]}...")
                
                # 发送到微信
                print("📤 发送到微信...")
                if self.send_to_wechat(reply):
                    self.stats["sent"] += 1
                    print("✅ 发送成功")
                else:
                    print("❌ 发送失败")
                
            except KeyboardInterrupt:
                print("\n\n正在退出...")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
        
        print(f"\n📊 统计: 收到 {self.stats['received']}, 发送 {self.stats['sent']}")
        print("👋 再见!")


if __name__ == "__main__":
    bot = SimpleMacBot()
    bot.run()
