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

    def test_window_fingerprint_identical_list_twice_second_empty(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        messages = [make_msg("a"), make_msg("b"), make_msg("c")]
        assert session.filter_new(messages) == messages
        # Exact same list should trigger window fingerprint dedup
        assert session.filter_new(messages) == []

    def test_echo_detection_filters_recent_sent_message(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat", echo_time_window=10.0)
        session.record_sent("收到了")
        echo_msg = make_msg("收到了", sender="Bot")
        result = session.filter_new([echo_msg])
        assert result == []

    def test_echo_detection_does_not_filter_after_time_window(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat", echo_time_window=0.1)
        session.record_sent("收到了")
        time.sleep(0.15)
        echo_msg = make_msg("收到了", sender="Bot")
        result = session.filter_new([echo_msg])
        assert result == [echo_msg]

    def test_context_dedup_filters_when_message_and_previous_both_in_history(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        msg1 = make_msg("first")
        msg2 = make_msg("second")

        # First call: both messages are new
        assert session.filter_new([msg1, msg2]) == [msg1, msg2]

        # Second call with same pair: context dedup should filter both
        # because both msg1 and msg2 are in seen_messages
        assert session.filter_new([msg1, msg2]) == []

    def test_context_dedup_single_seen_message_is_filtered(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        msg1 = make_msg("first")
        msg2 = make_msg("second")
        msg3 = make_msg("third")

        # First call: all three messages are new
        assert session.filter_new([msg1, msg2, msg3]) == [msg1, msg2, msg3]

        # Second call with only msg2: msg2 has been seen before,
        # so _find_similar_seen filters it out
        assert session.filter_new([msg2]) == []

    def test_empty_input_returns_empty_list(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        assert session.filter_new([]) == []

    def test_cooldown_detection_true_within_seconds(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        session.last_reply_time = time.time()
        assert session.is_in_cooldown(seconds=30.0) is True

    def test_cooldown_detection_false_after_seconds(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        session.last_reply_time = time.time() - 31.0
        assert session.is_in_cooldown(seconds=30.0) is False

    def test_cooldown_detection_false_when_never_replied(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        assert session.is_in_cooldown(seconds=30.0) is False

    def test_record_sent_appends_to_sent_messages(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        session.record_sent("hello")
        assert len(session.sent_messages) == 1
        assert session.sent_messages[0].text == "hello"

    def test_record_sent_updates_last_reply_time_and_reply_count(self):
        session = ChatSession(chat_id="c1", chat_name="TestChat")
        before = time.time()
        session.record_sent("hello")
        after = time.time()
        assert session.reply_count == 1
        assert before <= session.last_reply_time <= after
