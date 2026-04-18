"""
存储模块 - 负责数据持久化
"""
from .message_store import MessageStore, StoredMessage

__all__ = ['MessageStore', 'StoredMessage']
