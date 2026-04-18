"""
微信消息读取
从 SQLite 数据库读取消息
"""

import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class WeChatMessage:
    """微信消息对象"""
    msg_id: int
    chat_id: str
    sender: str
    content: str
    msg_type: int
    create_time: datetime
    
    @property
    def is_text(self) -> bool:
        return self.msg_type == 1
    
    @property
    def is_from_me(self) -> bool:
        # 需要根据实际数据库字段判断
        return False


class MessageReader:
    """
    微信消息读取器
    
    注意：需要先解密数据库才能使用
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
    
    def connect(self) -> bool:
        """连接数据库"""
        try:
            self.conn = sqlite3.connect(str(self.db_path))
            self.cursor = self.conn.cursor()
            return True
        except Exception as e:
            print(f"连接数据库失败: {e}")
            return False
    
    def get_messages(self, chat_id: str, limit: int = 10) -> List[WeChatMessage]:
        """
        获取指定聊天的消息
        
        注意：表结构和字段名需要根据实际数据库调整
        """
        if not self.cursor:
            return []
        
        try:
            # 微信数据库表结构可能不同，这里使用通用查询
            # 实际需要根据反编译结果调整
            query = """
                SELECT msgId, type, content, createTime, msgSource 
                FROM message 
                WHERE talker = ? 
                ORDER BY createTime DESC 
                LIMIT ?
            """
            
            self.cursor.execute(query, (chat_id, limit))
            rows = self.cursor.fetchall()
            
            messages = []
            for row in rows:
                msg = WeChatMessage(
                    msg_id=row[0],
                    chat_id=chat_id,
                    sender="unknown",  # 需要解析
                    content=row[2] or "",
                    msg_type=row[1],
                    create_time=datetime.fromtimestamp(row[3])
                )
                messages.append(msg)
            
            return messages
            
        except Exception as e:
            print(f"读取消息失败: {e}")
            return []
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()


class MockMessageReader:
    """Mock 消息读取器（用于测试）"""
    
    def __init__(self, db_path: Path = None):
        self.db_path = db_path
    
    def connect(self) -> bool:
        return True
    
    def get_messages(self, chat_id: str, limit: int = 10) -> List[WeChatMessage]:
        """返回模拟消息"""
        return [
            WeChatMessage(
                msg_id=1,
                chat_id=chat_id,
                sender="user",
                content=f"这是 {chat_id} 的测试消息",
                msg_type=1,
                create_time=datetime.now()
            )
        ]
    
    def close(self):
        pass


if __name__ == "__main__":
    # 测试
    reader = MockMessageReader()
    reader.connect()
    messages = reader.get_messages("test_chat")
    for msg in messages:
        print(f"[{msg.chat_id}] {msg.sender}: {msg.content}")
