"""
Mac 微信 Accessibility API 操作
基于 AppleScript 和 AXUIElement
"""

import subprocess
import time
from typing import Optional, List, Tuple

class WeChatMacRPA:
    """Mac 版微信 RPA 控制器"""
    
    def __init__(self):
        self.chat_window_name: Optional[str] = None
        self.bot_name: Optional[str] = None
    
    def find_wechat_window(self) -> bool:
        """查找微信窗口"""
        script = '''
        tell application "System Events"
            tell process "WeChat"
                return exists window 1
            end tell
        end tell
        '''
        result = self._run_applescript(script)
        return "true" in result.lower()
    
    def get_chat_list(self) -> List[str]:
        """获取聊天列表"""
        script = '''
        tell application "System Events"
            tell process "WeChat"
                set chatList to {}
                tell scroll area 1 of splitter group 1 of window 1
                    set uiElements to entire contents
                    repeat with elem in uiElements
                        try
                            if role of elem is "AXButton" then
                                set end of chatList to (name of elem as string)
                            end if
                        end try
                    end repeat
                end tell
                return chatList
            end tell
        end tell
        '''
        result = self._run_applescript(script)
        # 解析结果
        chats = [c.strip() for c in result.split(",") if c.strip()]
        return chats
    
    def open_chat(self, chat_name: str) -> bool:
        """打开指定聊天窗口"""
        script = f'''
        tell application "System Events"
            tell process "WeChat"
                set targetChat to "{chat_name}"
                
                -- 点击搜索框
                click text field 1 of splitter group 1 of window 1
                delay 0.5
                
                -- 输入聊天名称
                keystroke targetChat
                delay 1
                
                -- 按回车打开
                keystroke return
                delay 0.5
                
                return true
            end tell
        end tell
        '''
        result = self._run_applescript(script)
        self.chat_window_name = chat_name
        return "true" in result.lower()
    
    def send_message(self, message: str) -> bool:
        """发送消息到当前聊天窗口"""
        # 使用 pyautogui 更安全
        try:
            import pyautogui
            import pyperclip
            
            # 复制消息到剪贴板
            pyperclip.copy(message)
            
            # 激活微信
            subprocess.run(['osascript', '-e', 'tell application "WeChat" to activate'])
            time.sleep(0.5)
            
            # 粘贴并发送
            pyautogui.hotkey('command', 'v')
            time.sleep(0.2)
            pyautogui.press('return')
            
            return True
        except Exception as e:
            print(f"发送失败: {e}")
            return False
    
    def get_messages(self, count: int = 10) -> List[dict]:
        """
        获取当前聊天窗口的消息
        注意：Accessibility API 无法直接读取历史消息内容
        需要通过数据库解密获取
        """
        # 这里返回空列表，实际消息通过数据库读取
        return []
    
    def _run_applescript(self, script: str) -> str:
        """运行 AppleScript"""
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return "timeout"
        except Exception as e:
            return f"error: {e}"


def test_accessibility():
    """测试 Accessibility API"""
    rpa = WeChatMacRPA()
    
    print("测试 Mac 微信 RPA")
    print("-" * 40)
    
    # 检查微信是否运行
    if rpa.find_wechat_window():
        print("✅ 微信窗口已找到")
    else:
        print("❌ 微信未运行或窗口未找到")
        return
    
    # 测试发送消息（需要手动打开聊天窗口）
    print("\n请在微信中打开要发送的聊天窗口，然后按回车...")
    input()
    
    test_msg = "这是一条测试消息 [Mac RPA]"
    if rpa.send_message(test_msg):
        print(f"✅ 消息发送成功: {test_msg}")
    else:
        print("❌ 消息发送失败")


if __name__ == "__main__":
    test_accessibility()
