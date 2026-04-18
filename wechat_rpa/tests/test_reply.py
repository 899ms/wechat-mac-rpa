#!/usr/bin/env python3
"""Tests for L4 Reply modules."""

import pytest
from wechat_rpa.models.base import ChatMessage, SenderType
from wechat_rpa.session.chat_session import ChatSession
from wechat_rpa.reply.policy import ReplyPolicy
from wechat_rpa.reply.generator import ReplyGenerator


class TestReplyPolicy:
    def test_self_message_returns_false(self):
        policy = ReplyPolicy()
        session = ChatSession(chat_id="c1", chat_name="Friend")
        msg = ChatMessage(
            text="hello",
            sender="me",
            sender_type=SenderType.SELF,
            chat_name="Friend",
        )
        assert policy.should_reply(msg, session) is False

    def test_system_message_returns_false(self):
        policy = ReplyPolicy()
        session = ChatSession(chat_id="c1", chat_name="Friend")
        msg = ChatMessage(
            text="system alert",
            sender="system",
            sender_type=SenderType.SYSTEM,
            chat_name="Friend",
        )
        assert policy.should_reply(msg, session) is False

    def test_other_message_in_cooldown_returns_false(self):
        import time
        policy = ReplyPolicy()
        session = ChatSession(chat_id="c1", chat_name="Friend")
        session.last_reply_time = time.time()  # now => cooldown active
        msg = ChatMessage(
            text="hello",
            sender="friend",
            sender_type=SenderType.OTHER,
            chat_name="Friend",
        )
        assert policy.should_reply(msg, session) is False

    def test_group_chat_without_at_returns_false(self):
        policy = ReplyPolicy(require_at_in_group=True)
        session = ChatSession(chat_id="c1", chat_name="Group (3)")
        msg = ChatMessage(
            text="hello everyone",
            sender="friend",
            sender_type=SenderType.OTHER,
            chat_name="Group (3)",
            is_at_me=False,
        )
        assert policy.should_reply(msg, session) is False

    def test_group_chat_with_at_returns_true(self):
        policy = ReplyPolicy()
        session = ChatSession(chat_id="c1", chat_name="Group (3)")
        msg = ChatMessage(
            text="@me hello",
            sender="friend",
            sender_type=SenderType.OTHER,
            chat_name="Group (3)",
            is_at_me=True,
        )
        assert policy.should_reply(msg, session) is True

    def test_normal_private_chat_returns_true(self):
        policy = ReplyPolicy()
        session = ChatSession(chat_id="c1", chat_name="Alice")
        msg = ChatMessage(
            text="hello",
            sender="Alice",
            sender_type=SenderType.OTHER,
            chat_name="Alice",
        )
        assert policy.should_reply(msg, session) is True


class TestReplyGenerator:
    def test_returns_non_empty_string(self):
        gen = ReplyGenerator(llm_client=None)
        session = ChatSession(chat_id="c1", chat_name="Alice")
        msg = ChatMessage(
            text="hello",
            sender="Alice",
            sender_type=SenderType.OTHER,
            chat_name="Alice",
        )
        reply = gen.generate(msg, session)
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_handles_none_llm_client_gracefully(self):
        gen = ReplyGenerator(llm_client=None)
        session = ChatSession(chat_id="c1", chat_name="Alice")
        msg = ChatMessage(
            text="hello",
            sender="Alice",
            sender_type=SenderType.OTHER,
            chat_name="Alice",
        )
        reply = gen.generate(msg, session)
        assert isinstance(reply, str)
        assert len(reply) <= 50

    def test_fallback_when_llm_fails(self):
        class FailingLLM:
            def chat(self, *args, **kwargs):
                raise RuntimeError("LLM down")

        gen = ReplyGenerator(llm_client=FailingLLM())
        session = ChatSession(chat_id="c1", chat_name="Alice")
        msg = ChatMessage(
            text="hello",
            sender="Alice",
            sender_type=SenderType.OTHER,
            chat_name="Alice",
        )
        reply = gen.generate(msg, session)
        assert reply == "收到"
