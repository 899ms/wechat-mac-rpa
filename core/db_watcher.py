"""
FSEvents 文件监听
监控微信数据库变化
"""

import os
import time
from pathlib import Path
from typing import Callable, List
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent


class WeChatDBWatcher(FileSystemEventHandler):
    """
    微信数据库文件监听器
    
    使用 FSEvents (macOS 原生) 监控 msg_*.db 文件变化
    """
    
    def __init__(self, message_callback: Callable[[str, str], None]):
        """
        Args:
            message_callback: 回调函数 (chat_id, message_content)
        """
        self.message_callback = message_callback
        self.db_path = self._find_db_path()
        self.last_modified = {}
        self.observer = None
        
        print(f"📁 数据库目录: {self.db_path}")
    
    def _find_db_path(self) -> Path:
        """查找微信数据库路径"""
        base_path = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data"
        
        # 查找版本目录
        for version_dir in base_path.glob("Library/Application Support/com.tencent.xinWeChat/*"):
            if version_dir.is_dir():
                # 查找用户目录
                for user_dir in version_dir.glob("*/Message"):
                    if user_dir.is_dir():
                        return user_dir
        
        raise RuntimeError("未找到微信数据库目录")
    
    def on_modified(self, event):
        """文件修改回调"""
        if not event.is_directory:
            file_path = Path(event.src_path)
            
            # 只关注 msg_*.db 文件
            if file_path.name.startswith("msg_") and file_path.suffix == ".db":
                # 防抖处理
                now = time.time()
                last = self.last_modified.get(file_path, 0)
                
                if now - last > 1:  # 1秒内不重复处理
                    self.last_modified[file_path] = now
                    chat_id = file_path.stem  # msg_0, msg_1, etc.
                    print(f"📝 数据库变化: {chat_id}")
                    # 回调由上层处理
    
    def start(self):
        """开始监听"""
        self.observer = Observer()
        self.observer.schedule(self, str(self.db_path), recursive=False)
        self.observer.start()
        print(f"👂 开始监听数据库变化...")
    
    def stop(self):
        """停止监听"""
        if self.observer:
            self.observer.stop()
            self.observer.join()


class MockWatcher:
    """
    Mock 监听器（用于测试）
    手动输入模拟消息
    """
    
    def __init__(self, message_callback: Callable[[str, str], None]):
        self.message_callback = message_callback
    
    def start(self):
        """交互式输入"""
        print("\n🎮 Mock 模式 - 手动输入消息")
        print("格式: 聊天ID|消息内容")
        print("示例: 文件传输助手|你好")
        print("输入 'exit' 退出\n")
        
        while True:
            try:
                line = input("💬 ").strip()
                if line.lower() == 'exit':
                    break
                
                if '|' in line:
                    chat_id, message = line.split('|', 1)
                    self.message_callback(chat_id.strip(), message.strip())
                else:
                    print("❌ 格式错误，使用: 聊天ID|消息内容")
                    
            except KeyboardInterrupt:
                break
    
    def stop(self):
        pass


if __name__ == "__main__":
    # 测试
    def on_message(chat_id: str, content: str):
        print(f"收到消息 [{chat_id}]: {content}")
    
    # 使用 Mock 模式测试
    watcher = MockWatcher(on_message)
    watcher.start()
