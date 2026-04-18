#!/usr/bin/env python3
"""
Mac 微信全自动 RPA 机器人 v2.0

功能：
- FSEvents 实时监听微信数据库
- 自动解密读取新消息
- Kimi LLM 生成智能回复
- AppleScript 自动发送消息

⚠️ 需要关闭 SIP
"""

import os
import sys
import time
import subprocess
import sqlite3
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass

# 项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.llm_client import KimiClient


@dataclass
class WeChatMessage:
    """微信消息对象"""
    msg_id: int
    chat_id: str
    sender: str
    content: str
    msg_type: int
    create_time: datetime
    is_from_me: bool = False


class WeChatDBDecryptor:
    """
    微信数据库解密器
    
    Mac 微信使用 SQLCipher 加密
    需要 db_key 才能解密
    """
    
    def __init__(self, db_key: str):
        self.db_key = db_key
        self.decrypted_dbs: Dict[str, Path] = {}
    
    def decrypt_db(self, encrypted_db: Path, output_dir: Path) -> Optional[Path]:
        """
        解密单个数据库文件
        
        Args:
            encrypted_db: 加密的 msg_*.db 文件路径
            output_dir: 解密后文件存放目录
        
        Returns:
            解密后的数据库路径，失败返回 None
        """
        try:
            # 使用 sqlcipher 解密
            output_db = output_dir / f"{encrypted_db.stem}_decrypted.db"
            
            # 构造 sqlcipher 命令
            commands = f"""
            PRAGMA key = \"x'{self.db_key}'\";
            ATTACH DATABASE '{output_db}' AS plaintext KEY '';
            SELECT sqlcipher_export('plaintext');
            DETACH DATABASE plaintext;
            """
            
            result = subprocess.run(
                ['sqlcipher', str(encrypted_db)],
                input=commands,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if output_db.exists() and output_db.stat().st_size > 0:
                return output_db
            else:
                print(f"❌ 解密失败: {encrypted_db.name}")
                return None
                
        except Exception as e:
            print(f"❌ 解密异常: {e}")
            return None
    
    def decrypt_all(self, message_dir: Path, output_dir: Path) -> List[Path]:
        """解密所有 msg_*.db 文件"""
        decrypted = []
        
        for db_file in message_dir.glob("msg_*.db"):
            print(f"🔓 解密: {db_file.name}")
            result = self.decrypt_db(db_file, output_dir)
            if result:
                decrypted.append(result)
                print(f"   ✅ 成功: {result.name}")
        
        return decrypted


class MessageWatcher:
    """
    FSEvents 文件监听器
    监控微信数据库文件变化
    """
    
    def __init__(self, 
                 message_dir: Path,
                 decrypted_dir: Path,
                 db_key: str,
                 on_new_message: Callable[[WeChatMessage], None]):
        """
        Args:
            message_dir: 微信消息数据库目录
            decrypted_dir: 解密后数据库存放目录
            db_key: 数据库密钥
            on_new_message: 新消息回调函数
        """
        self.message_dir = message_dir
        self.decrypted_dir = decrypted_dir
        self.db_key = db_key
        self.on_new_message = on_new_message
        
        self.decryptor = WeChatDBDecryptor(db_key)
        self.last_msg_ids: Dict[str, int] = {}  # 记录每个数据库最后读取的 msg_id
        self.running = False
        
        print(f"👂 监听器初始化")
        print(f"   数据库目录: {message_dir}")
        print(f"   解密目录: {decrypted_dir}")
    
    def find_message_dir(self) -> Optional[Path]:
        """查找微信消息数据库目录"""
        base = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data"
        
        # 查找版本目录
        for version_dir in base.glob("Library/Application Support/com.tencent.xinWeChat/*"):
            if version_dir.is_dir():
                # 查找用户目录下的 Message
                for user_dir in version_dir.glob("*/Message"):
                    if user_dir.is_dir():
                        return user_dir
        
        return None
    
    def read_messages(self, db_path: Path, chat_id: str) -> List[WeChatMessage]:
        """
        从解密的数据库读取消息
        
        表结构参考:
        - message 表存储消息
        - 字段: msgId, type, content, createTime, talker, msgSource
        """
        messages = []
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # 获取该聊天最后读取的 msg_id
            last_id = self.last_msg_ids.get(chat_id, 0)
            
            # 查询新消息
            cursor.execute("""
                SELECT msgId, type, content, createTime, talker 
                FROM message 
                WHERE talker = ? AND msgId > ?
                ORDER BY msgId ASC
            """, (chat_id, last_id))
            
            for row in cursor.fetchall():
                msg = WeChatMessage(
                    msg_id=row[0],
                    chat_id=chat_id,
                    sender=row[4] or "unknown",
                    content=row[2] or "",
                    msg_type=row[1],
                    create_time=datetime.fromtimestamp(row[3]) if row[3] else datetime.now()
                )
                messages.append(msg)
                
                # 更新最后读取的 msg_id
                if row[0] > last_id:
                    last_id = row[0]
            
            self.last_msg_ids[chat_id] = last_id
            conn.close()
            
        except Exception as e:
            print(f"❌ 读取数据库失败: {e}")
        
        return messages
    
    def poll_loop(self, interval: float = 2.0):
        """
        轮询循环（替代 FSEvents，更可靠）
        
        Args:
            interval: 轮询间隔（秒）
        """
        print(f"🔄 启动轮询监听，间隔 {interval}s")
        print("按 Ctrl+C 停止\n")
        
        self.running = True
        
        while self.running:
            try:
                # 1. 解密所有数据库
                decrypted_dbs = self.decryptor.decrypt_all(
                    self.message_dir, 
                    self.decrypted_dir
                )
                
                # 2. 读取每个数据库的新消息
                for db_path in decrypted_dbs:
                    chat_id = db_path.stem.replace("_decrypted", "")
                    messages = self.read_messages(db_path, chat_id)
                    
                    for msg in messages:
                        # 只处理文本消息且不是自己的
                        if msg.msg_type == 1 and not msg.is_from_me:
                            self.on_new_message(msg)
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\n\n正在停止...")
                self.running = False
            except Exception as e:
                print(f"❌ 轮询异常: {e}")
                time.sleep(interval)


class AutoReplyBot:
    """
    全自动回复机器人
    """
    
    def __init__(self, db_key: str):
        self.db_key = db_key
        self.llm = KimiClient()
        self.stats = {"received": 0, "sent": 0}
        
        # 查找数据库目录
        self.message_dir = self._find_message_dir()
        self.decrypted_dir = Path(__file__).parent.parent / "db_decrypted"
        self.decrypted_dir.mkdir(exist_ok=True)
        
        # 创建监听器
        self.watcher = MessageWatcher(
            self.message_dir,
            self.decrypted_dir,
            db_key,
            self._on_new_message
        )
        
        print("🤖 全自动机器人初始化完成")
    
    def _find_message_dir(self) -> Path:
        """查找微信消息目录"""
        base = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data"
        
        for version_dir in base.glob("Library/Application Support/com.tencent.xinWeChat/*"):
            if version_dir.is_dir():
                for user_dir in version_dir.glob("*/Message"):
                    if user_dir.is_dir():
                        return user_dir
        
        raise RuntimeError("未找到微信消息目录")
    
    def _on_new_message(self, msg: WeChatMessage):
        """新消息回调"""
        print(f"\n📨 新消息 [{msg.chat_id}] {msg.sender}: {msg.content[:50]}...")
        self.stats["received"] += 1
        
        # 生成回复
        reply = self.llm.chat(
            msg.chat_id,
            msg.content,
            system_prompt="你是微信智能助手，回复简洁友好"
        )
        
        print(f"🤖 生成回复: {reply[:80]}...")
        
        # 发送回复
        if self._send_message(reply):
            self.stats["sent"] += 1
            print("✅ 发送成功")
        else:
            print("❌ 发送失败")
    
    def _send_message(self, message: str) -> bool:
        """使用 AppleScript 发送消息"""
        try:
            # 激活微信
            subprocess.run([
                'osascript', '-e',
                'tell application "WeChat" to activate'
            ])
            time.sleep(0.3)
            
            # 复制到粘贴板
            subprocess.run(['pbcopy'], input=message.encode('utf-8'))
            time.sleep(0.1)
            
            # 粘贴并发送
            script = '''
            tell application "System Events"
                tell process "WeChat"
                    keystroke "v" using command down
                    delay 0.2
                    keystroke return
                end tell
            end tell
            '''
            subprocess.run(['osascript', '-e', script])
            return True
            
        except Exception as e:
            print(f"发送失败: {e}")
            return False
    
    def run(self):
        """运行机器人"""
        print("\n" + "=" * 60)
        print("🤖 Mac 微信全自动 RPA 机器人 v2.0")
        print("=" * 60)
        print("\n⚠️  前置检查:")
        print("  1. SIP 已关闭: csrutil status")
        print("  2. 微信已登录并保持前台")
        print("  3. 已在微信中打开要监听的聊天窗口")
        print("  4. 已授权终端辅助功能权限")
        print("\n" + "=" * 60 + "\n")
        
        # 启动轮询
        self.watcher.poll_loop(interval=3.0)
        
        # 打印统计
        print(f"\n📊 统计: 收到 {self.stats['received']}, 发送 {self.stats['sent']}")


if __name__ == "__main__":
    # 从环境变量或配置文件读取 db_key
    db_key = os.getenv("WECHAT_DB_KEY")
    
    if not db_key:
        print("❌ 请设置数据库密钥:")
        print("   export WECHAT_DB_KEY=\"your_db_key_here\"")
        print("\n获取方法:")
        print("   1. 关闭 SIP")
        print("   2. 使用 wechat-dump 工具获取")
        sys.exit(1)
    
    bot = AutoReplyBot(db_key)
    bot.run()
