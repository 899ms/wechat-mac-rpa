#!/usr/bin/env python3
"""L4 ChatHistory 单元测试"""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from wechat_rpa.models.base import ChatMessage, SenderType
from wechat_rpa.storage.chat_history import ChatHistory, HistoryRecord


class TestHistoryRecord:
    """测试 HistoryRecord 数据模型"""

    def test_creation_minimal(self):
        r = HistoryRecord(text="hi", sender="Alice", sender_type="other", chat_name="测试群")
        assert r.text == "hi"
        assert r.sender == "Alice"
        assert r.sender_type == "other"
        assert r.chat_name == "测试群"
        assert r.is_at_me is False
        assert r.timestamp != ""
        assert r.message_hash != ""

    def test_hash_computed_correctly(self):
        r = HistoryRecord(text="hello", sender="Bob", sender_type="self", chat_name="群A", bubble_y=100)
        expected = HistoryRecord._compute_hash(r)
        assert r.message_hash == expected

    def test_custom_timestamp(self):
        ts = "2026-04-11T10:00:00"
        r = HistoryRecord(text="hi", sender="Alice", sender_type="other", chat_name="测试群", timestamp=ts)
        assert r.timestamp == ts

    def test_to_dict_roundtrip(self):
        r = HistoryRecord(
            text="hello",
            sender="Bot",
            sender_type="self",
            chat_name="测试群",
            is_at_me=True,
            timestamp="2026-04-11T10:00:00",
            message_hash="abc123",
            confidence=0.95,
            bubble_y=120,
            source="ocr",
            tick_id=42,
            screenshot_path="/tmp/test.png",
        )
        d = r.to_dict()
        r2 = HistoryRecord.from_dict(d)
        assert r2.text == "hello"
        assert r2.sender_type == "self"
        assert r2.confidence == pytest.approx(0.95)
        assert r2.tick_id == 42

    def test_from_dict_ignores_unknown_keys(self):
        d = {
            "text": "hi",
            "sender": "Alice",
            "sender_type": "other",
            "chat_name": "测试群",
            "unknown_field": "should_be_ignored",
        }
        r = HistoryRecord.from_dict(d)
        assert r.text == "hi"
        assert not hasattr(r, "unknown_field")


class TestChatHistory:
    """测试 ChatHistory 持久化存储"""

    @pytest.fixture
    def tmp_storage_dir(self, tmp_path):
        return tmp_path / "data"

    @pytest.fixture
    def history(self, tmp_storage_dir):
        return ChatHistory(storage_dir=str(tmp_storage_dir))

    def _make_chat_message(self, text, sender, sender_type, chat_name="测试群", is_at_me=False, timestamp=None):
        return ChatMessage(
            text=text,
            sender=sender,
            sender_type=sender_type,
            chat_name=chat_name,
            is_at_me=is_at_me,
            timestamp=timestamp,
        )

    def test_init_creates_directories(self, tmp_storage_dir, history):
        assert (tmp_storage_dir / "history").exists()
        assert (tmp_storage_dir / "logs").exists()

    def test_append_messages_with_chat_message(self, tmp_storage_dir, history):
        """append_messages 必须接受 List[ChatMessage]（ARCHITECTURE.md 2.13）"""
        messages = [
            self._make_chat_message("在吗", "小王", SenderType.OTHER),
            self._make_chat_message("在的", "Bot", SenderType.SELF, is_at_me=False, timestamp="12:34"),
        ]
        records = history.append_messages(chat_name="测试群", messages=messages, tick_id=1, screenshot_path="/tmp/1.png")

        assert len(records) == 2
        assert records[0].text == "在吗"
        assert records[0].sender_type == "other"
        assert records[1].text == "在的"
        assert records[1].sender_type == "self"
        assert records[1].tick_id == 1
        assert records[1].screenshot_path == "/tmp/1.png"

        # 验证 jsonl 文件已写入
        jsonl_path = tmp_storage_dir / "history" / "测试群.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        data = json.loads(lines[0])
        assert data["text"] == "在吗"

        # 验证 txt 日志已写入
        txt_path = tmp_storage_dir / "logs" / "chat_history.txt"
        assert txt_path.exists()
        txt_content = txt_path.read_text(encoding="utf-8")
        assert "在吗" in txt_content
        assert "在的" in txt_content

    def test_get_messages_by_chat_name(self, history):
        messages = [
            self._make_chat_message("msg1", "A", SenderType.OTHER, chat_name="群A"),
            self._make_chat_message("msg2", "B", SenderType.OTHER, chat_name="群B"),
        ]
        history.append_messages("群A", [messages[0]], tick_id=1)
        history.append_messages("群B", [messages[1]], tick_id=2)

        results = history.get_messages(chat_name="群A")
        assert len(results) == 1
        assert results[0].text == "msg1"
        assert results[0].chat_name == "群A"

    def test_get_messages_all_chats(self, history):
        history.append_messages("群A", [self._make_chat_message("a1", "A", SenderType.OTHER, chat_name="群A")], tick_id=1)
        history.append_messages("群B", [self._make_chat_message("b1", "B", SenderType.OTHER, chat_name="群B")], tick_id=2)

        results = history.get_messages()
        assert len(results) == 2
        texts = {r.text for r in results}
        assert texts == {"a1", "b1"}

    def test_get_messages_time_filter(self, history):
        now = datetime.now()
        old_msg = self._make_chat_message("old", "A", SenderType.OTHER, timestamp=(now - timedelta(hours=2)).isoformat())
        new_msg = self._make_chat_message("new", "B", SenderType.OTHER, timestamp=now.isoformat())

        history.append_messages("群A", [old_msg], tick_id=1)
        history.append_messages("群A", [new_msg], tick_id=2)

        since = now - timedelta(minutes=30)
        results = history.get_messages(chat_name="群A", since=since)
        assert len(results) == 1
        assert results[0].text == "new"

    def test_get_messages_limit(self, history):
        for i in range(5):
            history.append_messages("群A", [self._make_chat_message(f"m{i}", "U", SenderType.OTHER, chat_name="群A")], tick_id=i)

        results = history.get_messages(chat_name="群A", limit=3)
        assert len(results) == 3
        assert results[-1].text == "m4"

    def test_get_recent_chats(self, history):
        history.append_messages("群A", [self._make_chat_message("a", "U", SenderType.OTHER, chat_name="群A")], tick_id=1)
        history.append_messages("群B", [self._make_chat_message("b", "U", SenderType.OTHER, chat_name="群B")], tick_id=2)

        grouped = history.get_recent_chats(hours=24.0, limit=10)
        assert "群A" in grouped
        assert "群B" in grouped
        assert len(grouped["群A"]) == 1

    def test_get_last_message(self, history):
        history.append_messages("群A", [self._make_chat_message("first", "U", SenderType.OTHER, chat_name="群A")], tick_id=1)
        history.append_messages("群A", [self._make_chat_message("last", "U", SenderType.OTHER, chat_name="群A")], tick_id=2)

        last = history.get_last_message("群A")
        assert last is not None
        assert last.text == "last"

    def test_get_last_message_empty_chat(self, history):
        last = history.get_last_message("不存在的群")
        assert last is None

    def test_get_stats(self, history):
        history.append_messages("群A", [
            self._make_chat_message("a1", "U", SenderType.OTHER, chat_name="群A"),
            self._make_chat_message("a2", "Bot", SenderType.SELF, chat_name="群A"),
        ], tick_id=1)
        history.append_messages("群B", [
            self._make_chat_message("b1", "U", SenderType.OTHER, chat_name="群B"),
        ], tick_id=2)

        stats = history.get_stats()
        assert stats["total_messages"] == 3
        assert stats["unique_chats"] == 2
        assert stats["self_messages"] == 1
        assert stats["other_messages"] == 2
        assert stats["chat_files"] == 2

    def test_export_chat(self, tmp_storage_dir, history):
        history.append_messages("群A", [
            self._make_chat_message("hello", "U", SenderType.OTHER, chat_name="群A"),
        ], tick_id=1)

        export_path = history.export_chat("群A")
        assert Path(export_path).exists()
        data = json.loads(Path(export_path).read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["text"] == "hello"

    def test_export_chat_custom_path(self, tmp_storage_dir, history):
        history.append_messages("群A", [
            self._make_chat_message("hello", "U", SenderType.OTHER, chat_name="群A"),
        ], tick_id=1)

        custom_path = tmp_storage_dir / "exported.json"
        export_path = history.export_chat("群A", output_path=str(custom_path))
        assert export_path == str(custom_path)
        assert custom_path.exists()

    def test_slugify_special_chars(self, history):
        """特殊字符的聊天名应被安全地转为文件名"""
        history.append_messages("群/名?测试", [
            self._make_chat_message("hi", "U", SenderType.OTHER, chat_name="群/名?测试"),
        ], tick_id=1)

        jsonl_files = list((history.storage_dir / "history").glob("*.jsonl"))
        assert len(jsonl_files) == 1
        assert "群_名_测试" in jsonl_files[0].name

    def test_empty_chat_name_becomes_unknown(self, history):
        history.append_messages("", [self._make_chat_message("hi", "U", SenderType.OTHER, chat_name="")], tick_id=1)
        jsonl_files = list((history.storage_dir / "history").glob("*.jsonl"))
        assert any("_unknown" in f.name for f in jsonl_files)

    def test_sender_type_enum_converted_to_string(self, history):
        """ChatMessage 的 SenderType 枚举应自动转为字符串存储"""
        messages = [
            self._make_chat_message("m1", "U", SenderType.OTHER),
            self._make_chat_message("m2", "Bot", SenderType.SELF),
            self._make_chat_message("m3", "Sys", SenderType.SYSTEM),
        ]
        records = history.append_messages("测试群", messages, tick_id=1)
        assert records[0].sender_type == "other"
        assert records[1].sender_type == "self"
        assert records[2].sender_type == "system"

    def test_deduplication_not_performed(self, history):
        """ChatHistory 不应执行去重（去重由 ChatSession 负责）"""
        msg = self._make_chat_message("same", "U", SenderType.OTHER, chat_name="群A")
        history.append_messages("群A", [msg], tick_id=1)
        history.append_messages("群A", [msg], tick_id=2)

        results = history.get_messages(chat_name="群A")
        assert len(results) == 2
