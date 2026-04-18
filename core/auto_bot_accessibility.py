#!/usr/bin/env python3
"""
基于 Accessibility API 的全自动微信机器人
无需 db_key，直接读取微信界面消息
"""

import time
import subprocess
import re
from datetime import datetime
from typing import Optional, Callable
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_client import KimiClient


class WeChatAccessibilityBot:
    """基于 Accessibility API 的微信机器人"""
    
    def __init__(self):
        self.llm = KimiClient()
        self.last_message = ""
        self.running = False
        self.system_prompt = """你是微信智能助手，请遵守以下规则：
1. 回复简洁，适合微信阅读
2. 适当使用 emoji 增加亲和力
3. 技术问题给出代码示例
4. 不知道时诚实说不知道
5. 不要回复过长的内容"""
        
    def get_frontmost_app(self) -> str:
        """获取当前最前面的应用"""
        script = 'tell application "System Events" to get name of first application process whose frontmost is true'
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        return result.stdout.strip()
    
    def get_wechat_window_info(self) -> dict:
        """获取微信窗口信息"""
        script = '''
        tell application "System Events"
            tell process "WeChat"
                try
                    set winName to name of front window
                    return winName
                on error
                    return ""
                end try
            end tell
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        window_name = result.stdout.strip()
        
        # 解析窗口标题（通常是"用户名 - 聊天"格式）
        if " - " in window_name:
            chat_name = window_name.split(" - ")[0]
        else:
            chat_name = window_name
            
        return {
            "window_name": window_name,
            "chat_name": chat_name
        }
    
    def get_selected_text(self) -> str:
        """获取选中的文本（用于读取消息）"""
        # 先尝试复制当前选中的内容
        script = '''
        tell application "System Events"
            keystroke "c" using command down
        end tell
        '''
        subprocess.run(['osascript', '-e', script], capture_output=True)
        time.sleep(0.1)
        
        # 然后读取剪贴板
        result = subprocess.run(['pbpaste'], capture_output=True, text=True)
        return result.stdout.strip()
    
    def get_last_message_via_clipboard(self) -> str:
        """通过复制获取最后一条消息"""
        # 保存当前剪贴板
        old_clipboard = subprocess.run(['pbpaste'], capture_output=True, text=True).stdout
        
        # 聚焦微信窗口
        self.focus_wechat()
        time.sleep(0.2)
        
        # 按 End 键到消息底部
        script = '''
        tell application "System Events"
            tell process "WeChat"
                key code 119  -- End key
                delay 0.1
                keystroke "a" using command down
                delay 0.1
                keystroke "c" using command down
            end tell
        end tell
        '''
        subprocess.run(['osascript', '-e', script], capture_output=True)
        time.sleep(0.2)
        
        # 读取剪贴板
        result = subprocess.run(['pbpaste'], capture_output=True, text=True)
        message = result.stdout.strip()
        
        # 恢复剪贴板
        subprocess.run(['echo', old_clipboard], stdout=subprocess.PIPE)
        subprocess.run(['pbcopy'], input=old_clipboard.encode())
        
        return message
    
    def focus_wechat(self):
        """聚焦微信窗口"""
        script = '''
        tell application "WeChat"
            activate
        end tell
        '''
        subprocess.run(['osascript', '-e', script], capture_output=True)
        time.sleep(0.2)
    
    def send_message(self, message: str):
        """发送消息到微信"""
        # 聚焦微信
        self.focus_wechat()
        time.sleep(0.2)
        
        # 复制消息到剪贴板
        subprocess.run(['echo', message], stdout=subprocess.PIPE)
        subprocess.run(['pbcopy'], input=message.encode())
        time.sleep(0.1)
        
        # 粘贴并发送
        script = '''
        tell application "System Events"
            tell process "WeChat"
                keystroke "v" using command down
                delay 0.1
                keystroke return
            end tell
        end tell
        '''
        subprocess.run(['osascript', '-e', script], capture_output=True)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 已发送: {message[:50]}...")
    
    def check_for_new_messages(self) -> Optional[str]:
        """检查是否有新消息"""
        # 获取当前窗口信息
        win_info = self.get_wechat_window_info()
        chat_name = win_info.get("chat_name", "")
        
        if not chat_name:
            return None
        
        # 尝试获取最新消息
        # 方法：使用 AppleScript 获取微信窗口中的文本元素
        script = '''
        tell application "System Events"
            tell process "WeChat"
                try
                    set msgList to {}
                    repeat with elem in (every UI element of scroll area 1 of splitter group 1 of window 1 whose role description is "文本")
                        set end of msgList to value of elem
                    end repeat
                    return (item -1 of msgList) as string
                on error errMsg
                    return ""
                end try
            end tell
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        message = result.stdout.strip()
        
        if message and message != self.last_message and len(message) > 0:
            self.last_message = message
            return message
        
        return None
    
    def process_message(self, message: str, chat_name: str):
        """处理消息并回复"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{chat_name}] 收到: {message[:50]}...")
        
        # 调用 LLM 生成回复
        user_id = f"wechat_{chat_name}"
        reply = self.llm.chat(user_id, message, self.system_prompt)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] AI回复: {reply[:50]}...")
        
        # 发送回复
        self.send_message(reply)
    
    def run(self, interval: float = 3.0):
        """运行机器人"""
        print("=" * 60)
        print("🤖 微信全自动机器人 (Accessibility API 版)")
        print("=" * 60)
        print()
        print("⚠️  使用说明:")
        print("1. 确保微信已登录")
        print("2. 保持微信窗口可见（不要最小化）")
        print("3. 机器人会自动读取最后一条消息")
        print("4. 按 Ctrl+C 停止")
        print()
        print(f"检查间隔: {interval} 秒")
        print()
        
        self.running = True
        
        try:
            while self.running:
                # 检查微信是否运行
                result = subprocess.run(['pgrep', 'WeChat'], capture_output=True)
                if result.returncode != 0:
                    print("❌ 微信未运行，等待...")
                    time.sleep(interval)
                    continue
                
                # 获取窗口信息
                win_info = self.get_wechat_window_info()
                chat_name = win_info.get("chat_name", "")
                
                if not chat_name:
                    time.sleep(interval)
                    continue
                
                # 检查新消息
                new_message = self.check_for_new_messages()
                if new_message:
                    self.process_message(new_message, chat_name)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 机器人已停止")
            self.running = False


if __name__ == "__main__":
    bot = WeChatAccessibilityBot()
    bot.run(interval=3.0)
