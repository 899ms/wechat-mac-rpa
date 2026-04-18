#!/usr/bin/env python3
"""
基于 Quartz/CoreGraphics 的全自动微信机器人
无需辅助功能权限
"""

import time
import subprocess
from datetime import datetime
from typing import Optional
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_client import KimiClient


class WeChatQuartzBot:
    """基于 Quartz 的微信机器人"""
    
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
        
    def focus_wechat(self):
        """聚焦微信窗口"""
        subprocess.run(['osascript', '-e', 'tell application "WeChat" to activate'], 
                      capture_output=True)
        time.sleep(0.3)
    
    def get_wechat_window_title(self) -> str:
        """获取微信窗口标题"""
        script = '''
        tell application "WeChat"
            try
                set winName to name of front window
                return winName
            on error
                return ""
            end try
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        return result.stdout.strip()
    
    def read_clipboard(self) -> str:
        """读取剪贴板内容"""
        result = subprocess.run(['pbpaste'], capture_output=True, text=True)
        return result.stdout.strip()
    
    def write_clipboard(self, text: str):
        """写入剪贴板"""
        subprocess.run(['pbcopy'], input=text.encode())
    
    def get_selected_text(self) -> str:
        """获取选中的文本"""
        # 保存当前剪贴板
        old_clipboard = self.read_clipboard()
        
        # 复制选中的内容
        self.focus_wechat()
        subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "c" using command down'], 
                      capture_output=True)
        time.sleep(0.2)
        
        # 读取剪贴板
        text = self.read_clipboard()
        
        # 恢复剪贴板
        self.write_clipboard(old_clipboard)
        
        return text
    
    def get_last_message(self) -> str:
        """获取最后一条消息"""
        # 保存当前剪贴板
        old_clipboard = self.read_clipboard()
        
        self.focus_wechat()
        time.sleep(0.2)
        
        # 按 Cmd+A 全选，然后复制
        script = '''
        tell application "System Events"
            keystroke "a" using command down
            delay 0.1
            keystroke "c" using command down
        end tell
        '''
        subprocess.run(['osascript', '-e', script], capture_output=True)
        time.sleep(0.3)
        
        # 读取剪贴板
        text = self.read_clipboard()
        
        # 恢复剪贴板
        self.write_clipboard(old_clipboard)
        
        return text
    
    def send_message(self, message: str):
        """发送消息"""
        # 保存当前剪贴板
        old_clipboard = self.read_clipboard()
        
        self.focus_wechat()
        time.sleep(0.2)
        
        # 写入消息到剪贴板
        self.write_clipboard(message)
        time.sleep(0.1)
        
        # 粘贴并发送
        script = '''
        tell application "System Events"
            keystroke "v" using command down
            delay 0.1
            keystroke return
        end tell
        '''
        subprocess.run(['osascript', '-e', script], capture_output=True)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 已发送: {message[:50]}...")
        
        # 恢复剪贴板
        time.sleep(0.2)
        self.write_clipboard(old_clipboard)
    
    def extract_last_message(self, text: str) -> str:
        """从复制的文本中提取最后一条消息"""
        # 简单处理：取最后几行
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if len(lines) >= 2:
            # 倒数第二行通常是最后一条消息（最后一行可能是输入框）
            return lines[-2]
        elif len(lines) == 1:
            return lines[0]
        return ""
    
    def should_reply(self, message: str) -> bool:
        """判断是否需要回复"""
        # 过滤掉自己的消息（简单判断：包含"我"或太短的消息）
        if len(message) < 2:
            return False
        # 如果是重复消息
        if message == self.last_message:
            return False
        return True
    
    def process_message(self, message: str, chat_name: str):
        """处理消息"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{chat_name}] 收到: {message[:50]}...")
        
        # 调用 LLM
        user_id = f"wechat_{chat_name}"
        reply = self.llm.chat(user_id, message, self.system_prompt)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] AI回复: {reply[:50]}...")
        
        # 发送
        self.send_message(reply)
        
        self.last_message = message
    
    def run(self, interval: float = 3.0):
        """运行机器人"""
        print("=" * 60)
        print("🤖 微信全自动机器人 (Quartz API 版)")
        print("=" * 60)
        print()
        print("⚠️  使用说明:")
        print("1. 确保微信已登录")
        print("2. 保持微信窗口在前台")
        print("3. 打开一个聊天窗口")
        print("4. 按 Ctrl+C 停止")
        print()
        print(f"检查间隔: {interval} 秒")
        print()
        
        self.running = True
        
        # 获取初始聊天名称
        chat_name = self.get_wechat_window_title()
        if chat_name:
            print(f"当前聊天: {chat_name}")
        
        try:
            while self.running:
                # 检查微信是否运行
                result = subprocess.run(['pgrep', 'WeChat'], capture_output=True)
                if result.returncode != 0:
                    print("❌ 微信未运行，等待...")
                    time.sleep(interval)
                    continue
                
                # 获取当前聊天名称
                current_chat = self.get_wechat_window_title()
                if current_chat:
                    chat_name = current_chat
                
                if not chat_name:
                    time.sleep(interval)
                    continue
                
                # 获取消息
                text = self.get_last_message()
                message = self.extract_last_message(text)
                
                if message and self.should_reply(message):
                    self.process_message(message, chat_name)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 机器人已停止")
            self.running = False


if __name__ == "__main__":
    bot = WeChatQuartzBot()
    bot.run(interval=3.0)
