#!/usr/bin/env python3
"""GlobalStore 单元测试"""

import json
import os
import tempfile

import pytest

from wechat_rpa.session.global_store import GlobalStore, _msg_id, ChatState
from wechat_rpa.models.base import ChatMessage, SenderType


class TestMsgId:
    def test_msg_id_deterministic(self):
        """相同消息生成相同 ID"""
        msg = ChatMessage(text="hello", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        assert _msg_id("群1", msg) == _msg_id("群1", msg)

    def test_msg_id_differs_by_chat(self):
        """不同聊天生成不同 ID"""
        m1 = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        m2 = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群2")
        assert _msg_id("群1", m1) != _msg_id("群2", m2)


class TestGlobalStore:
    @pytest.fixture
    def store(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        yield GlobalStore(state_file=path)
        os.unlink(path)

    def test_merge_tick_new_messages(self, store):
        """首次 merge 返回所有消息为未回复"""
        msg = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        state, unreplied = store.merge_tick("群1", [msg])
        assert len(unreplied) == 1
        assert unreplied[0].text == "hi"
        assert isinstance(state, ChatState)

    def test_merge_tick_deduplication(self, store):
        """相同消息多次 merge 不重复堆积（消息体只存一份，但未回复的仍会返回）"""
        msg = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        store.merge_tick("群1", [msg])
        state, unreplied = store.merge_tick("群1", [msg])
        # 消息不重复堆积
        assert len(state.messages) == 1
        # 但未回复的遗留消息仍会返回
        assert len(unreplied) == 1
        assert unreplied[0].text == "hi"

    def test_merge_tick_same_tick_duplicates(self, store):
        """同一 tick 内传入重复消息只保留一条"""
        msg = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        state, unreplied = store.merge_tick("群1", [msg, msg, msg])
        assert len(unreplied) == 1
        assert len(state.messages) == 1

    def test_merge_tick_excludes_self(self, store):
        """自己消息不算未回复"""
        msg = ChatMessage(text="ok", sender="me", sender_type=SenderType.SELF, chat_name="群1")
        state, unreplied = store.merge_tick("群1", [msg])
        assert len(unreplied) == 0

    def test_mark_replied(self, store):
        """标记回复后消息不再出现在未回复列表"""
        msg = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        store.merge_tick("群1", [msg])
        store.mark_replied("群1", msg, "收到")

        state, unreplied = store.merge_tick("群1", [])
        assert len(unreplied) == 0
        assert state.messages[0].replied is True
        assert state.messages[0].reply_text == "收到"

    def test_get_unreplied_ordered(self, store):
        """未回复消息按时间顺序返回"""
        m1 = ChatMessage(text="a", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        m2 = ChatMessage(text="b", sender="B", sender_type=SenderType.OTHER, chat_name="群1")
        store.merge_tick("群1", [m1])
        store.merge_tick("群1", [m2])
        unreplied = store.get_unreplied("群1")
        assert [m.text for m in unreplied] == ["a", "b"]

    def test_max_messages_limit(self, store):
        """超过 max_messages 裁剪旧消息"""
        store.max_messages = 3
        for i in range(5):
            msg = ChatMessage(text=str(i), sender="A", sender_type=SenderType.OTHER, chat_name="群1")
            store.merge_tick("群1", [msg])
        state, _ = store.merge_tick("群1", [])
        assert len(state.messages) == 3
        assert state.messages[0].text == "2"

    def test_persistence_roundtrip(self, store):
        """持久化后加载能恢复状态"""
        msg = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        store.merge_tick("群1", [msg])
        store.mark_replied("群1", msg, "ok")
        store.save()

        # 重新加载
        store2 = GlobalStore(state_file=store._state_file)
        state, unreplied = store2.merge_tick("群1", [])
        assert len(unreplied) == 0
        assert len(state.messages) == 1
        assert state.messages[0].replied is True
        assert state.messages[0].reply_text == "ok"

    def test_reply_count_and_last_reply_time(self, store):
        """从消息推导回复统计"""
        msg = ChatMessage(text="hi", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        store.merge_tick("群1", [msg])
        assert store.reply_count("群1") == 0
        assert store.last_reply_time("群1") is None

        store.mark_replied("群1", msg, "收到")
        assert store.reply_count("群1") == 1
        assert store.last_reply_time("群1") is not None

    def test_multiple_chats_isolated(self, store):
        """不同聊天互不影响"""
        m1 = ChatMessage(text="a", sender="A", sender_type=SenderType.OTHER, chat_name="群1")
        m2 = ChatMessage(text="b", sender="B", sender_type=SenderType.OTHER, chat_name="群2")
        store.merge_tick("群1", [m1])
        store.merge_tick("群2", [m2])
        assert len(store.get_unreplied("群1")) == 1
        assert len(store.get_unreplied("群2")) == 1
