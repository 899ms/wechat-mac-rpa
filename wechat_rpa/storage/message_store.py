#!/usr/bin/env python3
"""
消息存储模块

负责消息的持久化和去重
"""

import os
import json
import hashlib
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path


@dataclass
class StoredMessage:
    """存储的消息"""
    text: str
    sender: str
    sender_type: str
    chat_name: str
    is_at_me: bool = False
    timestamp: str = ""
    message_hash: str = ""
    confidence: float = 0.0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if not self.message_hash:
            self.message_hash = self._compute_hash()
    
    def _compute_hash(self) -> str:
        """计算消息哈希"""
        content = f"{self.chat_name}:{self.sender}:{self.text}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()


class MessageStore:
    """消息存储管理器"""
    
    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.expanduser("~/wechat-mac-rpa/data")
        
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.screenshots_dir = self.storage_dir / "screenshots"
        self.screenshots_dir.mkdir(exist_ok=True)
        
        self.logs_dir = self.storage_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)
        
        # 内存缓存
        self._cache: Dict[str, StoredMessage] = {}
        
        # 加载历史
        self._load_history()
    
    def _load_history(self):
        """加载历史消息"""
        history_file = self.logs_dir / "message_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 获取 StoredMessage 的合法字段，过滤掉旧版本遗留字段（如 bubble_y）
                    valid_fields = {f for f in StoredMessage.__dataclass_fields__}
                    for item in data:
                        filtered = {k: v for k, v in item.items() if k in valid_fields}
                        msg = StoredMessage(**filtered)
                        self._cache[msg.message_hash] = msg
                print(f"📚 已加载 {len(self._cache)} 条历史消息")
            except Exception as e:
                print(f"⚠️ 加载历史失败: {e}")
    
    def _save_history(self):
        """保存历史消息"""
        history_file = self.logs_dir / "message_history.json"
        try:
            data = [
                {
                    'text': msg.text,
                    'sender': msg.sender,
                    'sender_type': msg.sender_type,
                    'chat_name': msg.chat_name,
                    'is_at_me': msg.is_at_me,
                    'timestamp': msg.timestamp,
                    'message_hash': msg.message_hash,
                    'confidence': float(msg.confidence)
                }
                for msg in self._cache.values()
            ]
            data.sort(key=lambda x: x['timestamp'])
            
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存历史失败: {e}")
    
    def save_screenshot(self, image_path: str, session_id: str = None) -> str:
        """保存截图"""
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"wechat_{session_id}_{timestamp}.png"
        filepath = self.screenshots_dir / filename
        
        import shutil
        shutil.copy2(image_path, filepath)
        
        return str(filepath)
    
    def add_messages(self, messages: List[StoredMessage], session_id: str = None) -> List[StoredMessage]:
        """
        添加消息，返回新增（去重后）的消息
        
        Args:
            messages: 消息列表
            session_id: 会话 ID
            
        Returns:
            新增的消息列表
        """
        new_messages = []
        
        for msg in messages:
            if msg.message_hash not in self._cache:
                self._cache[msg.message_hash] = msg
                new_messages.append(msg)
        
        if new_messages:
            self._save_history()
            self._append_to_text_log(new_messages, session_id)
        
        return new_messages
    
    def _append_to_text_log(self, messages: List[StoredMessage], session_id: str = None):
        """追加到文本日志"""
        log_file = self.logs_dir / "chat_history.txt"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            for msg in messages:
                time_str = msg.timestamp.split('T')[1][:8] if 'T' in msg.timestamp else msg.timestamp
                sender_icon = "🤖" if msg.sender_type == "self" else "👤"
                at_flag = " [@]" if msg.is_at_me else ""
                f.write(f"[{time_str}] [{msg.chat_name}] {sender_icon} {msg.sender}{at_flag}: {msg.text}\n")
    
    def get_messages(self, chat_name: str = None, limit: int = 100) -> List[StoredMessage]:
        """获取消息历史"""
        messages = list(self._cache.values())
        if chat_name:
            messages = [m for m in messages if m.chat_name == chat_name]
        messages.sort(key=lambda m: m.timestamp)
        return messages[-limit:]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        messages = list(self._cache.values())
        chat_names = set(m.chat_name for m in messages)
        
        return {
            "total_messages": len(messages),
            "unique_chats": len(chat_names),
            "self_messages": sum(1 for m in messages if m.sender_type == "self"),
            "other_messages": sum(1 for m in messages if m.sender_type == "other"),
            "screenshots": len(list(self.screenshots_dir.glob("*.png"))),
            "storage_dir": str(self.storage_dir)
        }
    
    def is_duplicate(self, message: StoredMessage) -> bool:
        """检查消息是否已存在"""
        return message.message_hash in self._cache
