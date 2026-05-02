#!/usr/bin/env python3
"""Tests for ChatSession - L4 Session layer."""

import time
import pytest
from wechat_rpa.models.base import ChatMessage, SenderType
from wechat_rpa.session.chat_session import ChatSession


def make_msg(text: str, sender: str = "Alice", chat_name: str = "TestChat") -> ChatMessage:
    return ChatMessage(
        text=text,
        sender=sender,
        sender_type=SenderType.OTHER,
        chat_name=chat_name,
    )


class TestChatSession:
    def test_first_time_messages_returned_as_new(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        messages = [make_msg("hello"), make_msg("world")]
        result = session.filter_new(messages)
        assert result == messages

    def test_exact_duplicates_filtered_on_second_call(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        messages = [make_msg("hello"), make_msg("world")]
        assert session.filter_new(messages) == messages
        assert session.filter_new(messages) == []

    def test_context_dedup_filters_when_message_and_previous_both_in_history(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        msg1 = make_msg("first")
        msg2 = make_msg("second")

        assert session.filter_new([msg1, msg2]) == [msg1, msg2]
        assert session.filter_new([msg1, msg2]) == []

    def test_context_dedup_single_seen_message_is_filtered(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        msg1 = make_msg("first")
        msg2 = make_msg("second")
        msg3 = make_msg("third")

        assert session.filter_new([msg1, msg2, msg3]) == [msg1, msg2, msg3]
        assert session.filter_new([msg2]) == []

    def test_empty_input_returns_empty_list(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        assert session.filter_new([]) == []

    def test_record_sent_updates_last_reply_time_and_reply_count(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        before = time.time()
        session.record_sent("hello")
        after = time.time()
        assert session.reply_count == 1
        assert before <= session.last_reply_time <= after
