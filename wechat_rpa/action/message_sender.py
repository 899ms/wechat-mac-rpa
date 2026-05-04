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
            r1 = subprocess.run(
                ["osascript", "-e", 'tell application "WeChat" to activate'],
                timeout=3,
                capture_output=True,
            )
            if r1.returncode != 0:
                err = r1.stderr.decode("utf-8", errors="replace") if r1.stderr else "unknown"
                return ActionResult(success=False, error=f"激活微信失败: {err}")
            time.sleep(0.1)

            # 2. 复制消息到剪贴板
            r2 = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                timeout=2,
                capture_output=True,
            )
            if r2.returncode != 0:
                err = r2.stderr.decode("utf-8", errors="replace") if r2.stderr else "unknown"
                return ActionResult(success=False, error=f"复制剪贴板失败: {err}")
            time.sleep(0.15)

            # 3. 确保焦点在输入框：先点一下窗口中心偏下区域（输入框大致位置）
            focus_script = """
                tell application "System Events"
                    tell process "WeChat"
                        set frontmost to true
                        delay 0.2
                        -- 获取窗口大小，点击底部中央（输入框区域）
                        tell window 1
                            set winPos to position
                            set winSize to size
                            set clickX to (item 1 of winPos) + (item 1 of winSize) / 2
                            set clickY to (item 2 of winPos) + (item 2 of winSize) - 40
                        end tell
                        click at {clickX, clickY}
                        delay 0.2
                    end tell
                end tell
            """
            subprocess.run(["osascript", "-e", focus_script], timeout=5, capture_output=True)

            # 4. 粘贴并发送
            script = """
                tell application "System Events"
                    tell process "WeChat"
                        keystroke "v" using command down
                        delay 0.3
                        keystroke return
                    end tell
                end tell
            """
            r3 = subprocess.run(
                ["osascript", "-e", script],
                timeout=5,
                capture_output=True,
            )
            if r3.returncode != 0:
                err = r3.stderr.decode("utf-8", errors="replace") if r3.stderr else "unknown"
                return ActionResult(success=False, error=f"粘贴发送失败: {err}")

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
