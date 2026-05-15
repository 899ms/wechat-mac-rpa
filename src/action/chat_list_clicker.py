#!/usr/bin/env python3
"""L5 Action - 点击聊天列表项切换窗口

将 OCR/Layouter 识别的 ChatListItem 转换为屏幕点击动作。
坐标计算规则：
- item.rect 是截图中的像素坐标（Retina 实际像素）
- window_rect 是屏幕逻辑坐标（AppleScript 报告的尺寸）
- screen_abs = window_rect + item_rect / scale_factor
"""

import subprocess
from typing import Optional

from src.models.base import ChatListItem, Rect


class ChatListClicker:
    """点击左侧聊天列表中的指定项，切换当前聊天窗口。"""

    def __init__(self, window_rect: Rect, scale_factor: float = 2.0):
        self.window_rect = window_rect
        self.scale_factor = scale_factor

    def click_item(self, item: ChatListItem) -> bool:
        """
        点击聊天列表项的中心位置。

        策略：
        1. 先激活微信窗口（确保有焦点）
        2. 点击位置取列表项中心（rect 包含昵称+预览，x 偏移确保在条目内）
        3. 点击后等待右侧展开，避免快速连续点击导致误触

        Args:
            item: 要点击的 ChatListItem，包含 rect（截图像素坐标）

        Returns:
            True 如果点击命令执行成功
        """
        # 点击位置：取 rect 中心，避免偏左偏右点到相邻项
        click_x = item.rect.x + item.rect.width // 2
        click_y = item.rect.y + item.rect.height // 2

        abs_x = int(self.window_rect.x + click_x / self.scale_factor)
        abs_y = int(self.window_rect.y + click_y / self.scale_factor)

        try:
            # Step 1: 激活微信窗口
            subprocess.run(
                ["osascript", "-e", 'tell application "WeChat" to activate'],
                timeout=3,
                capture_output=True,
            )
            # Step 2: 等待窗口激活 + 避免快速连续点击
            import time
            time.sleep(0.8)
            # Step 3: 点击
            subprocess.run(
                ["/opt/homebrew/bin/cliclick", f"c:{abs_x},{abs_y}"],
                check=True,
                timeout=5,
            )
            # Step 4: 点击后等待右侧展开稳定
            time.sleep(0.5)
            return True
        except Exception:
            return False

    def click_by_index(self, items: list[ChatListItem], index: int) -> bool:
        """按索引点击列表项。"""
        if 0 <= index < len(items):
            return self.click_item(items[index])
        return False

    def click_first_unread(
        self, items: list[ChatListItem], exclude_nickname: Optional[str] = None
    ) -> Optional[ChatListItem]:
        """
        点击第一个有未读消息的聊天项（排除当前已打开的聊天）。

        Args:
            items: 聊天列表项
            exclude_nickname: 要排除的聊天名称（通常是当前聊天）

        Returns:
            被点击的 ChatListItem，如果没有则返回 None
        """
        for item in items:
            if not item.unread_count:
                continue
            if exclude_nickname and item.nickname == exclude_nickname:
                continue
            if self.click_item(item):
                return item
        return None
