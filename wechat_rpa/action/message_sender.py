#!/usr/bin/env python3
"""L4 Action Layer - Message Sender

负责发送消息到微信窗口。
"""

import subprocess
import time
from abc import ABC, abstractmethod

from wechat_rpa.models.base import ActionResult


class MessageSender(ABC):
    """消息发送器抽象基类"""

    @abstractmethod
    def send(self, text: str) -> ActionResult:
        """发送文本消息"""
        pass

    @abstractmethod
    def send_image(self, image_path: str) -> ActionResult:
        """发送图片消息"""
        pass

    @abstractmethod
    def send_file(self, file_path: str) -> ActionResult:
        """发送文件"""
        pass


class WeChatMessageSender(MessageSender):
    """基于 AppleScript 的微信消息发送器"""

    def send(self, text: str) -> ActionResult:
        """
        发送文本消息到当前微信聊天。

        流程：
        1. 激活 WeChat 窗口
        2. 将文本复制到剪贴板 (pbcopy)
        3. 通过 AppleScript 执行 Command+V 粘贴并回车发送
        """
        try:
            # 1. 确保微信窗口在前台，防止消息发到其他应用
            subprocess.run(
                ["osascript", "-e", 'tell application "WeChat" to activate'],
                timeout=3,
                capture_output=True,
            )
            time.sleep(0.1)

            # 2. 复制消息到剪贴板
            subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                timeout=2,
            )
            time.sleep(0.15)

            # 3. 粘贴并发送
            # 禁忌：不能用 keystroke "a" using command down（中文 IME 会产生产拼音碎片）
            script = """
                tell application "System Events"
                    tell process "WeChat"
                        keystroke "v" using command down
                        delay 0.15
                        keystroke return
                    end tell
                end tell
            """
            subprocess.run(
                ["osascript", "-e", script],
                timeout=5,
                capture_output=True,
            )

            return ActionResult(success=True, sent_text=text)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def send_image(self, image_path: str) -> ActionResult:
        """预留：将图片复制到剪贴板后 Command+V 粘贴发送。"""
        return ActionResult(
            success=False,
            error="send_image is not implemented yet",
        )

    def send_file(self, file_path: str) -> ActionResult:
        """预留：拖拽文件到输入框或复制到剪贴板后粘贴发送。"""
        return ActionResult(
            success=False,
            error="send_file is not implemented yet",
        )
