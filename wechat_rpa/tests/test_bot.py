#!/usr/bin/env python3
"""L5 Bot Orchestrator 单元测试"""

import time
import pytest
from unittest.mock import Mock, patch

from wechat_rpa.bot.wechat_bot import WeChatBot
from wechat_rpa.layout.profile import PROFILE_WECHAT_MAC_1760X1280
from wechat_rpa.models.base import (
    ChatMessage, ChatListItem, PerceptionResult,
    ActionResult, SenderType, Rect, Point
)


class TestWeChatBot:
    @pytest.fixture
    def bot(self):
        return WeChatBot(PROFILE_WECHAT_MAC_1760X1280)

    def test_tick_no_new_messages(self, bot):
        """没有新消息时不发送回复"""
        mock_result = PerceptionResult(
            chat_name="测试群",
            messages=[ChatMessage(text="旧消息", sender="A", sender_type=SenderType.OTHER, chat_name="测试群")],
            chat_list_items=[],
            screenshot_path="/tmp/1.png"
        )
        bot.perception = Mock()
        bot.perception.perceive.return_value = mock_result

        # 模拟 session 返回空（消息都已见过）
        with patch.object(bot, '_get_session') as mock_get_session:
            mock_session = Mock()
            mock_session.filter_new.return_value = []
            mock_get_session.return_value = mock_session

            bot.tick()

            bot.perception.perceive.assert_called_once()
            mock_session.filter_new.assert_called_once()
            mock_session.record_sent.assert_not_called()

    def test_tick_replies_to_new_message(self, bot):
        """有新消息且 policy 允许时发送回复"""
        msg = ChatMessage(text="在吗", sender="A", sender_type=SenderType.OTHER, chat_name="测试群")
        mock_result = PerceptionResult(
            chat_name="测试群",
            messages=[msg],
            chat_list_items=[],
            screenshot_path="/tmp/2.png"
        )
        bot.perception = Mock()
        bot.perception.perceive.return_value = mock_result

        bot.policy = Mock()
        bot.policy.should_reply.return_value = True

        bot.generator = Mock()
        bot.generator.generate.return_value = "在的"

        bot.sender = Mock()
        bot.sender.send.return_value = ActionResult(success=True, sent_text="在的")

        with patch.object(bot, '_get_session') as mock_get_session:
            mock_session = Mock()
            mock_session.filter_new.return_value = [msg]
            mock_session.is_in_cooldown.return_value = False
            mock_get_session.return_value = mock_session

            bot.tick()

            bot.generator.generate.assert_called_once()
            bot.sender.send.assert_called_once_with("在的")
            mock_session.record_sent.assert_called_once_with("在的")

    def test_tick_perception_none(self, bot):
        """perceive 返回 None 时直接跳过"""
        bot.perception = Mock()
        bot.perception.perceive.return_value = None

        bot.tick()

        bot.perception.perceive.assert_called_once()

    def test_tick_policy_declines(self, bot):
        """policy 返回 False 时不生成回复"""
        msg = ChatMessage(text="在吗", sender="A", sender_type=SenderType.OTHER, chat_name="测试群")
        mock_result = PerceptionResult(
            chat_name="测试群",
            messages=[msg],
            chat_list_items=[],
            screenshot_path="/tmp/3.png"
        )
        bot.perception = Mock()
        bot.perception.perceive.return_value = mock_result

        bot.policy = Mock()
        bot.policy.should_reply.return_value = False

        bot.generator = Mock()
        bot.sender = Mock()

        with patch.object(bot, '_get_session') as mock_get_session:
            mock_session = Mock()
            mock_session.filter_new.return_value = [msg]
            mock_get_session.return_value = mock_session

            bot.tick()

            bot.generator.generate.assert_not_called()
            bot.sender.send.assert_not_called()

    def test_on_message_callback(self, bot):
        """on_message 回调被正确触发"""
        callback = Mock()
        bot.on_message = callback

        msg = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="测试群")
        mock_result = PerceptionResult(
            chat_name="测试群",
            messages=[msg],
            chat_list_items=[],
            screenshot_path="/tmp/4.png"
        )
        bot.perception = Mock()
        bot.perception.perceive.return_value = mock_result

        with patch.object(bot, '_get_session') as mock_get_session:
            mock_session = Mock()
            mock_session.filter_new.return_value = [msg]
            mock_get_session.return_value = mock_session

            bot.tick()

            callback.assert_called_once_with(msg, mock_session)

    def test_send_to_chat(self, bot):
        """send_to_chat 主动发送接口"""
        bot.sender = Mock()
        bot.sender.send.return_value = ActionResult(success=True, sent_text="hello")

        result = bot.send_to_chat("测试群", "hello")

        assert result.success is True
        bot.sender.send.assert_called_once_with("hello")

    def test_no_switch_when_only_no_reply_chats_have_unread(self, bot):
        """
        只有免回复聊天（如腾讯新闻）有未读时，不应触发切换。

        问题来源：2026-04-19 排查发现所有 tick 的 switch_reason='无未读项'，
        实际是因为唯一未读来自 "腾讯新闻"（在 no_reply_chats 中），被过滤后
        unread_items 为空。
        """
        mock_result = PerceptionResult(
            chat_name="",
            messages=[],
            chat_list_items=[
                ChatListItem(nickname="腾讯新闻", last_message_preview="...", unread_count="1", timestamp="", rect=Rect(0, 0, 0, 0)),
                ChatListItem(nickname="文件传输助手", last_message_preview="...", unread_count="", timestamp="", rect=Rect(0, 0, 0, 0)),
            ],
            screenshot_path="/tmp/1.png",
            window_rect=Rect(0, 0, 100, 100),
            scale_factor=1.0,
            debug_info={"screenshot_path": "/tmp/1.png"},
        )
        bot.perception = Mock()
        bot.perception.perceive.return_value = mock_result

        # tick() 内部会调用 _try_switch_to_unread_chat
        # 在 save() 被调用时（finally 块中）捕获状态，因为 save() 后 current 会被重置为 None
        captured = {}
        def _capture_save():
            captured['action'] = bot.debug_logger.current.action
            captured['switch_reason'] = bot.debug_logger.current.bot_switch_reason
            return __import__('pathlib').Path("data/debug/test.json")

        with patch.object(bot.debug_logger, 'save', side_effect=_capture_save):
            with patch.object(bot, '_get_session') as mock_get_session:
                mock_session = Mock()
                mock_session.filter_new.return_value = []
                mock_get_session.return_value = mock_session

                bot.tick()

        # 不应产生 switch action，而是 none（聊天名为空且无未读）
        assert captured['action'] == "none"
        assert "无未读项" in captured['switch_reason']

    def test_switch_to_highest_unread_non_no_reply_chat(self, bot):
        """
        有多个未读时，应切换到未读数最多的非免回复聊天。

        问题来源：2026-04-19 tick 7205-7207 因 "王芊 @ai开发小…" 有 101 条未读
        而触发 switch，这是正确行为。本测试验证该逻辑。
        """
        mock_result = PerceptionResult(
            chat_name="",
            messages=[],
            chat_list_items=[
                ChatListItem(nickname="腾讯新闻", last_message_preview="...", unread_count="3", timestamp="", rect=Rect(0, 0, 0, 0)),
                ChatListItem(nickname="王芊 @ai开发小分队", last_message_preview="...", unread_count="101", timestamp="", rect=Rect(0, 0, 0, 0)),
                ChatListItem(nickname="普通群", last_message_preview="...", unread_count="5", timestamp="", rect=Rect(0, 0, 0, 0)),
            ],
            screenshot_path="/tmp/2.png",
            window_rect=Rect(0, 0, 100, 100),
            scale_factor=1.0,
            debug_info={"screenshot_path": "/tmp/2.png"},
        )
        bot.perception = Mock()
        bot.perception.perceive.return_value = mock_result

        # Mock ChatListClicker 避免真实点击
        with patch("wechat_rpa.bot.wechat_bot.ChatListClicker") as mock_clicker_class:
            mock_clicker = Mock()
            mock_clicker.click_item.return_value = True
            mock_clicker_class.return_value = mock_clicker

            # 在 save() 被调用时捕获状态
            captured = {}
            def _capture_save():
                captured['switch_target'] = bot.debug_logger.current.bot_switch_target
                captured['switch_reason'] = bot.debug_logger.current.bot_switch_reason
                captured['action'] = bot.debug_logger.current.action
                return __import__('pathlib').Path("data/debug/test.json")

            with patch.object(bot.debug_logger, 'save', side_effect=_capture_save):
                with patch.object(bot, '_get_session') as mock_get_session:
                    mock_session = Mock()
                    mock_session.filter_new.return_value = []
                    mock_get_session.return_value = mock_session

                    bot.tick()

        # 应切换到未读数最多的非免回复聊天
        assert captured['switch_target'] == "王芊 @ai开发小分队"
        assert "未读 101" in captured['switch_reason']
