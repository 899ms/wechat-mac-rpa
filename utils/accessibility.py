"""
Mac Accessibility API 封装
用于发送消息到微信
"""

import subprocess
import time
import platform


class WeChatAccessibility:
    """微信 Accessibility 控制器"""
    
    def __init__(self):
        if platform.system() != "Darwin":
            raise RuntimeError("仅支持 macOS")
    
    def activate_wechat(self):
        """激活微信窗口"""
        script = 'tell application "WeChat" to activate'
        subprocess.run(['osascript', '-e', script])
        time.sleep(0.3)
    
    def send_message(self, message: str) -> bool:
        """
        发送消息到当前聊天窗口
        
        注意：需要先在微信中打开目标聊天窗口
        """
        try:
            import pyautogui
            import pyperclip
            
            # 激活微信
            self.activate_wechat()
            
            # 复制消息
            pyperclip.copy(message)
            
            # 粘贴
            pyautogui.keyDown('command')
            pyautogui.keyDown('v')
            pyautogui.keyUp('v')
            pyautogui.keyUp('command')
            
            time.sleep(0.2)
            
            # 发送
            pyautogui.press('return')
            
            return True
        except Exception as e:
            print(f"发送失败: {e}")
            return False
    
    def open_chat(self, chat_name: str) -> bool:
        """
        打开指定聊天窗口
        使用搜索功能
        """
        try:
            import pyautogui
            
            self.activate_wechat()
            
            # Command+F 打开搜索
            pyautogui.keyDown('command')
            pyautogui.keyDown('f')
            pyautogui.keyUp('f')
            pyautogui.keyUp('command')
            
            time.sleep(0.3)
            
            # 输入聊天名称
            pyautogui.typewrite(chat_name, interval=0.01)
            time.sleep(0.5)
            
            # 回车打开
            pyautogui.press('return')
            time.sleep(0.3)
            
            return True
        except Exception as e:
            print(f"打开聊天失败: {e}")
            return False


if __name__ == "__main__":
    wx = WeChatAccessibility()
    print("测试发送消息...")
    wx.send_message("测试消息 [Mac RPA]")
