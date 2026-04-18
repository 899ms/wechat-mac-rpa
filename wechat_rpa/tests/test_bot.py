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
