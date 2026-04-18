#!/usr/bin/env python3
"""
基于剪贴板的微信 RPA 机器人（修复版）

核心逻辑：
1. 用户复制任何消息 → 触发回复
2. 机器人回复后，剪贴板会变为回复内容
3. 下一轮检测时，如果剪贴板还是回复内容 → 不触发（避免循环）
4. 用户再次复制消息（即使内容相同）→ 触发回复
"""

import time
import subprocess
import hashlib
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_client import KimiClient


class WeChatClipboardBot:
    """基于剪贴板的微信机器人"""
    
    def __init__(self):
        self.llm = KimiClient()
        self.last_clipboard = ""  # 上次处理的内容
        self.running = False
        self.system_prompt = """你是微信智能助手，请遵守以下规则：
1. 回复简洁，适合微信阅读
2. 适当使用 emoji 增加亲和力
3. 技术问题给出代码示例
4. 不知道时诚实说不知道
5. 不要回复过长的内容"""
        
    def read_clipboard(self) -> str:
        """读取剪贴板内容"""
        try:
            result = subprocess.run(['pbpaste'], capture_output=True, text=True, timeout=2)
            return result.stdout.strip()
        except:
            return ""
    
    def write_clipboard(self, text: str):
        """写入剪贴板"""
        try:
            subprocess.run(['pbcopy'], input=text.encode(), timeout=2)
        except:
            pass
    
    def focus_wechat(self):
        """聚焦微信窗口"""
        subprocess.run(['osascript', '-e', 'tell application "WeChat" to activate'], 
                      capture_output=True, timeout=5)
        time.sleep(0.3)
    
    def send_message(self, message: str):
        """发送消息到微信"""
        self.focus_wechat()
        time.sleep(0.2)
        
        # 写入消息到剪贴板
        self.write_clipboard(message)
        time.sleep(0.15)
        
        # 粘贴并发送
        script = '''
        tell application "System Events"
            tell process "WeChat"
                keystroke "v" using command down
                delay 0.15
                keystroke return
            end tell
        end tell
        '''
        subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5)
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] ✉️ 已发送: {message[:60]}{'...' if len(message) > 60 else ''}")
        
        # 关键：更新 last_clipboard 为刚刚发送的回复
        # 这样下一轮如果剪贴板还是这个回复，就不会触发
        self.last_clipboard = message
    
    def should_reply(self, message: str) -> bool:
        """判断是否需要回复"""
        if not message or len(message.strip()) < 2:
            return False
        
        # 过滤系统消息
        system_keywords = ['[图片]', '[视频]', '[语音]', '[文件]', '[动画表情]', '撤回了一条消息']
        for kw in system_keywords:
            if kw in message:
                return False
        
        return True
    
    def generate_reply(self, message: str) -> str:
        """生成回复"""
        try:
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"[{timestamp}] 🤔 AI 思考中...")
            
            reply = self.llm.chat('wechat_user', message, self.system_prompt)
            return reply
        except Exception as e:
            print(f"❌ AI 调用失败: {e}")
            return "抱歉，我这边有点问题，稍后再试 😅"
    
    def run(self, interval: float = 2.0):
        """运行机器人"""
        print("=" * 60)
        print("🤖 微信剪贴板 RPA 机器人（修复版）")
        print("=" * 60)
        print()
        print("📱 使用方法：")
        print("   1. 在微信中选中对方消息")
        print("   2. 按 Cmd+C 复制")
        print("   3. 机器人自动检测 → AI 回复 → 自动发送")
        print()
        print("✅ 支持：重复复制相同内容")
        print("❌ 过滤：机器人自己的回复不会循环触发")
        print()
        print("⚠️  按 Ctrl+C 停止")
        print()
        
        # 初始化：读取当前剪贴板作为基准
        self.last_clipboard = self.read_clipboard()
        self.running = True
        
        try:
            while self.running:
                # 检查微信是否运行
                result = subprocess.run(['pgrep', 'WeChat'], capture_output=True, timeout=5)
                if result.returncode != 0:
                    time.sleep(interval)
                    continue
                
                # 读取当前剪贴板
                current = self.read_clipboard()
                
                # 检测逻辑：
                # 1. 剪贴板非空
                # 2. 剪贴板内容和上次处理的不同
                # 这样就能支持：
                # - 复制新内容 → 触发
                # - 重复复制相同内容 → 触发（因为 last 是机器人回复）
                # - 机器人自己的回复 → 不触发（因为 last 就是回复本身）
                if current and current != self.last_clipboard:
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    print(f"[{timestamp}] 📋 检测到: {current[:80]}{'...' if len(current) > 80 else ''}")
                    
                    # 判断是否需要回复
                    if self.should_reply(current):
                        reply = self.generate_reply(current)
                        
                        if reply:
                            print(f"[{timestamp}] 💬 AI: {reply[:80]}{'...' if len(reply) > 80 else ''}")
                            self.send_message(reply)
                    else:
                        print(f"[{timestamp}] ⏭️  跳过系统消息")
                        # 更新 last，避免重复检测
                        self.last_clipboard = current
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 机器人已停止")
            self.running = False


if __name__ == "__main__":
    bot = WeChatClipboardBot()
    bot.run(interval=2.0)
