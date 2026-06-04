#!/usr/bin/env python3
"""ChatListClicker 单元测试"""

import pytest
from unittest.mock import patch, MagicMock

from src.action.chat_list_clicker import ChatListClicker
from src.models.base import ChatListItem, Rect


class TestChatListClicker:
    def test_click_item_coordinates(self):
        """验证坐标计算：屏幕绝对坐标 = 窗口逻辑坐标 + 截图像素坐标 / scale_factor"""
        window_rect = Rect(x=100, y=200, width=800, height=600)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)

        item = ChatListItem(
            nickname="测试",
            last_message_preview="",
            unread_count="",
            timestamp="",
            rect=Rect(x=200, y=300, width=100, height=50),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            clicker.click_item(item)

            # 第一次调用是 activate，第二次是 cliclick
            cliclick_call = mock_run.call_args_list[1]
            args = cliclick_call[0][0]
            # click_x = 200 + 100//2 = 250, click_y = 300 + 50//2 = 325
            # abs_x = 100 + 250/2 = 225, abs_y = 200 + 325/2 = 362
            assert args[0] == "/opt/homebrew/bin/cliclick"
            assert args[1] == "c:225,362"

    def test_click_item_returns_true_on_success(self):
        window_rect = Rect(x=0, y=0, width=100, height=100)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)
        item = ChatListItem(nickname="test", last_message_preview="", unread_count="", timestamp="", rect=Rect(x=10, y=10, width=20, height=20))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = clicker.click_item(item)
            assert result is True

    def test_click_item_returns_false_on_failure(self):
        window_rect = Rect(x=0, y=0, width=100, height=100)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)
        item = ChatListItem(nickname="test", last_message_preview="", unread_count="", timestamp="", rect=Rect(x=10, y=10, width=20, height=20))

        with patch("subprocess.run", side_effect=Exception("cliclick not found")):
            result = clicker.click_item(item)
            assert result is False

    def test_click_by_index_valid(self):
        window_rect = Rect(x=0, y=0, width=100, height=100)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)
        items = [
            ChatListItem(nickname="a", last_message_preview="", unread_count="", timestamp="", rect=Rect(x=0, y=0, width=10, height=10)),
            ChatListItem(nickname="b", last_message_preview="", unread_count="", timestamp="", rect=Rect(x=0, y=10, width=10, height=10)),
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = clicker.click_by_index(items, 1)
            assert result is True

    def test_click_by_index_out_of_range(self):
        window_rect = Rect(x=0, y=0, width=100, height=100)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)
        items = [ChatListItem(nickname="a", last_message_preview="", unread_count="", timestamp="", rect=Rect(x=0, y=0, width=10, height=10))]
        result = clicker.click_by_index(items, 5)
        assert result is False

    def test_click_first_unread_found(self):
        window_rect = Rect(x=0, y=0, width=100, height=100)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)
        items = [
            ChatListItem(nickname="a", last_message_preview="", unread_count="", timestamp="", rect=Rect(x=0, y=0, width=10, height=10)),
            ChatListItem(nickname="b", last_message_preview="", unread_count="3", timestamp="", rect=Rect(x=0, y=10, width=10, height=10)),
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = clicker.click_first_unread(items)
            assert result is not None
            assert result.nickname == "b"

    def test_click_first_unread_excludes_current(self):
        window_rect = Rect(x=0, y=0, width=100, height=100)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)
        items = [
            ChatListItem(nickname="current", last_message_preview="", unread_count="3", timestamp="", rect=Rect(x=0, y=0, width=10, height=10)),
            ChatListItem(nickname="other", last_message_preview="", unread_count="5", timestamp="", rect=Rect(x=0, y=10, width=10, height=10)),
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = clicker.click_first_unread(items, exclude_nickname="current")
            assert result is not None
            assert result.nickname == "other"

    def test_click_first_unread_none_found(self):
        window_rect = Rect(x=0, y=0, width=100, height=100)
        clicker = ChatListClicker(window_rect, scale_factor=2.0)
        items = [
            ChatListItem(nickname="a", last_message_preview="", unread_count="", timestamp="", rect=Rect(x=0, y=0, width=10, height=10)),
        ]
        result = clicker.click_first_unread(items)
        assert result is None
