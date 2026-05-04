#!/usr/bin/env python3
"""
ChatHistory - 结构化聊天记录存储

设计目标：
1. 按聊天名称分文件存储（避免单文件过大）
2. 使用 JSON Lines 格式（便于追加、grep、流式读取）
3. 保留旧版 message_history.json 的兼容性
4. 支持按时间范围查询和统计

AI 使用指南：
- 新增记录：append_messages(chat_name, messages)
- 查询记录：get_messages(chat_name, since, until, limit)
- 备份/迁移：history_dir 下的所有 .jsonl 文件可直接复制
"""

import os
import json
import hashlib
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Union
import re


@dataclass
class HistoryRecord:
    """单条历史记录（兼容旧版 StoredMessage + 扩展字段）"""
    text: str
    sender: str
    sender_type: str
    chat_name: str
    is_at_me: bool = False
    timestamp: str = ""
    message_hash: str = ""
    confidence: float = 0.0
    bubble_y: int = 0
    source: str = "ocr"          # 来源：ocr / manual / api
    tick_id: int = 0             # 所属 tick 编号
    screenshot_path: str = ""    # 关联截图路径
    message_type: str = "text"   # text / image / sticker / mixed / link_card
    image_description: str = ""  # 图片描述
    image_text: str = ""         # 图片上的文字

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if not self.message_hash:
            self.message_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        content = f"{self.chat_name}:{self.sender}:{self.text}:{self.bubble_y}:{self.message_type}:{self.image_description}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HistoryRecord":
        # 过滤掉类中不存在的字段，保证向前兼容
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


class ChatHistory:
    """
    结构化聊天记录管理器。

    目录结构：
    {storage_dir}/
        history/
            {chat_name_slug}.jsonl      # 按聊天分文件
        logs/
            message_history.json        # 旧版兼容（聚合所有消息）
            chat_history.txt            # 人类可读文本日志
    """

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            storage_dir = os.path.expanduser("~/wechat-mac-rpa/data")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.history_dir = self.storage_dir / "history"
        self.history_dir.mkdir(exist_ok=True)

        self.logs_dir = self.storage_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)

        # 内存缓存（仅保留最近 2000 条，避免无限增长）
        self._cache: List[HistoryRecord] = []
        self._cache_limit = 2000

        # 加载旧版历史到缓存（一次性迁移）
        self._migrate_legacy_history()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _slugify(self, chat_name: str) -> str:
        """将聊天名称转换为安全文件名"""
        if not chat_name:
            return "_unknown"
        slug = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", chat_name)
        return slug[:80] or "_unknown"

    def _history_path(self, chat_name: str) -> Path:
        return self.history_dir / f"{self._slugify(chat_name)}.jsonl"

    def _parse_ts(self, ts: str) -> datetime:
        """尽可能解析 ISO 格式时间戳"""
        # 处理带 Z 或不带 Z 的情况
        ts = ts.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return datetime.min

    # ------------------------------------------------------------------
    # 迁移兼容
    # ------------------------------------------------------------------
    def _migrate_legacy_history(self):
        """如果存在旧版 message_history.json，将其迁移到新的分文件格式"""
        legacy_file = self.logs_dir / "message_history.json"
        if not legacy_file.exists():
            return

        try:
            with open(legacy_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            migrated_count = 0
            for item in data:
                record = HistoryRecord.from_dict(item)
                self._append_to_jsonl(record, flush=False)
                migrated_count += 1

            # 迁移完成后备份旧文件
            backup_path = self.logs_dir / f"message_history.json.bak.{datetime.now().strftime('%Y%m%d')}"
            shutil.move(str(legacy_file), str(backup_path))

            print(f"📚 已从旧版迁移 {migrated_count} 条历史记录 | 备份: {backup_path.name}")
        except Exception as e:
            print(f"⚠️ 迁移旧版历史失败: {e}")

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def _append_to_jsonl(self, record: HistoryRecord, flush: bool = True):
        """追加到对应聊天的 jsonl 文件"""
        path = self._history_path(record.chat_name)
        with open(path, "a", encoding="utf-8", buffering=1) as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def _append_to_text_log(self, records: List[HistoryRecord]):
        """追加到人类可读的文本日志"""
        log_file = self.logs_dir / "chat_history.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            for r in records:
                time_str = r.timestamp.split("T")[1][:8] if "T" in r.timestamp else r.timestamp
                sender_icon = "🤖" if r.sender_type == "self" else "👤"
                at_flag = " [@]" if r.is_at_me else ""
                f.write(f"[{time_str}] [{r.chat_name}] {sender_icon} {r.sender}{at_flag}: {r.text}\n")

    def append_messages(self, chat_name: str, messages: List[Any], tick_id: int = 0,
                        screenshot_path: str = "") -> List[HistoryRecord]:
        """
        批量追加消息到历史记录。

        Args:
            chat_name: 聊天名称
            messages: ChatMessage 列表（ARCHITECTURE.md 2.13）
            tick_id: 可选的 tick 编号
            screenshot_path: 关联截图路径

        Returns:
            实际追加的 HistoryRecord 列表
        """
        # 延迟导入避免循环依赖
        from wechat_rpa.models.base import ChatMessage

        records: List[HistoryRecord] = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                sender_type_str = msg.sender_type.value if hasattr(msg.sender_type, "value") else str(msg.sender_type)
                record = HistoryRecord(
                    text=msg.text,
                    sender=msg.sender,
                    sender_type=sender_type_str,
                    chat_name=chat_name,
                    is_at_me=msg.is_at_me,
                    timestamp=msg.timestamp or "",
                    confidence=0.0,
                    bubble_y=0,
                    source="ocr",
                    tick_id=tick_id,
                    screenshot_path=screenshot_path,
                    message_type=msg.message_type,
                    image_description=msg.image_description,
                    image_text=msg.image_text,
                )
            elif isinstance(msg, dict):
                record = HistoryRecord(
                    text=msg.get("text", ""),
                    sender=msg.get("sender", ""),
                    sender_type=msg.get("sender_type", "other"),
                    chat_name=chat_name,
                    is_at_me=msg.get("is_at_me", False),
                    timestamp=msg.get("timestamp", ""),
                    confidence=msg.get("confidence", 0.0),
                    bubble_y=msg.get("bubble_y", 0),
                    source=msg.get("source", "ocr"),
                    tick_id=tick_id,
                    screenshot_path=screenshot_path,
                    message_type=msg.get("message_type", "text"),
                    image_description=msg.get("image_description", ""),
                    image_text=msg.get("image_text", ""),
                )
            else:
                raise TypeError(f"Unsupported message type: {type(msg)}")
            records.append(record)

        # 写入 jsonl + text log + cache
        for r in records:
            self._append_to_jsonl(r)
            self._cache.append(r)
            if len(self._cache) > self._cache_limit:
                self._cache.pop(0)

        if records:
            self._append_to_text_log(records)

        return records

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def get_messages(self, chat_name: Optional[str] = None, since: Optional[datetime] = None,
                     until: Optional[datetime] = None, limit: int = 500) -> List[HistoryRecord]:
        """
        查询历史消息。

        Args:
            chat_name: 聊天名称，None 表示所有聊天
            since: 起始时间
            until: 结束时间
            limit: 最大返回条数
        """
        results: List[HistoryRecord] = []

        if chat_name:
            files = [self._history_path(chat_name)]
        else:
            files = sorted(self.history_dir.glob("*.jsonl"))

        for path in files:
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            record = HistoryRecord.from_dict(data)
                            ts = self._parse_ts(record.timestamp)
                            if since and ts < since:
                                continue
                            if until and ts > until:
                                continue
                            results.append(record)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue

        results.sort(key=lambda r: self._parse_ts(r.timestamp))
        return results[-limit:]

    def get_recent_chats(self, hours: float = 24.0, limit: int = 100) -> Dict[str, List[HistoryRecord]]:
        """获取最近 N 小时内有消息的聊天，按聊天分组"""
        since = datetime.now() - timedelta(hours=hours)
        messages = self.get_messages(since=since, limit=limit * 10)
        grouped: Dict[str, List[HistoryRecord]] = {}
        for m in messages:
            grouped.setdefault(m.chat_name, []).append(m)
        # 限制每个聊天的消息数
        for k in grouped:
            grouped[k] = grouped[k][-limit:]
        return grouped

    def get_last_message(self, chat_name: str) -> Optional[HistoryRecord]:
        """获取某个聊天的最后一条消息"""
        msgs = self.get_messages(chat_name=chat_name, limit=1)
        return msgs[0] if msgs else None

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_records = 0
        chat_files = list(self.history_dir.glob("*.jsonl"))
        chat_names = set()
        self_count = 0
        other_count = 0

        for path in chat_files:
            # 从文件名推断聊天名（可能不完全精确，但足够统计）
            chat_slug = path.stem
            chat_names.add(chat_slug)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            total_records += 1
                            try:
                                data = json.loads(line)
                                st = data.get("sender_type", "other")
                                if st == "self":
                                    self_count += 1
                                else:
                                    other_count += 1
                            except json.JSONDecodeError:
                                continue
            except Exception:
                continue

        return {
            "total_messages": total_records,
            "unique_chats": len(chat_names),
            "self_messages": self_count,
            "other_messages": other_count,
            "history_dir": str(self.history_dir),
            "chat_files": len(chat_files),
        }

    def export_chat(self, chat_name: str, output_path: Optional[str] = None) -> str:
        """导出某个聊天的完整记录为 JSON"""
        messages = self.get_messages(chat_name=chat_name, limit=10000)
        data = [m.to_dict() for m in messages]
        if output_path is None:
            output_path = self.history_dir / f"{self._slugify(chat_name)}_export.json"
        else:
            output_path = Path(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(output_path)
