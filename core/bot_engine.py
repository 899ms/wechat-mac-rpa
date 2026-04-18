"""
Mac 微信机器人引擎
整合：监听 + LLM + 发送
"""

import sys
import time
from pathlib import Path
from typing import Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.llm_client import KimiClient
from utils.accessibility import WeChatAccessibility
from core.message_reader import MockMessageReader
from core.db_watcher import MockWatcher


class MacWeChatBot:
    """
    Mac 微信全自动机器人
    
    架构：
    1. FSEvents 监听数据库变化
    2. 读取新消息
    3. Kimi LLM 生成回复
    4. Accessibility API 发送消息
    """
    
    def __init__(self, use_mock: bool = True):
        """
        Args:
            use_mock: 是否使用 Mock 模式（无需解密数据库）
        """
        self.use_mock = use_mock
        
        # 初始化组件
        print("🤖 初始化 Mac 微信机器人...")
        
        # LLM 客户端
        self.llm = KimiClient()
        print("✅ Kimi 客户端就绪")
        
        # 消息发送
        self.wechat = WeChatAccessibility()
        print("✅ Accessibility API 就绪")
        
        # 消息读取（Mock 模式）
        self.reader = MockMessageReader()
        self.reader.connect()
        print("✅ 消息读取器就绪")
        
        # 数据库监听
        self.watcher = MockWatcher(self._on_message)
        print("✅ 监听器就绪")
        
        # 统计
        self.stats = {"received": 0, "sent": 0}
        
        print("\n" + "=" * 50)
        print("🚀 机器人初始化完成")
        print("=" * 50)
    
    def _on_message(self, chat_id: str, content: str):
        """
        收到消息的回调
        
        流程：
        1. 判断是否处理该消息
        2. 调用 LLM 生成回复
        3. 发送回复到微信
        """
        print(f"\n📨 收到消息 [{chat_id}]: {content[:50]}...")
        self.stats["received"] += 1
        
        # 跳过自己的消息
        if content.startswith("[Bot]"):
            print("  ↪️ 跳过自己的消息")
            return
        
        # 特殊命令
        if content.strip() == "/帮助":
            reply = """🤖 Mac 微信机器人

/帮助 - 显示帮助
/清除 - 清除对话历史
/状态 - 查看统计

直接聊天即可与 AI 对话~"""
        elif content.strip() == "/清除":
            self.llm.clear_history(chat_id)
            reply = "🧹 对话历史已清除"
        elif content.strip() == "/状态":
            reply = f"📊 统计\n收到: {self.stats['received']}\n发送: {self.stats['sent']}"
        else:
            # 调用 LLM
            print("  🤔 调用 Kimi 生成回复...")
            reply = self.llm.chat(
                chat_id, 
                content,
                system_prompt="你是微信智能助手，回复简洁友好，适当使用emoji"
            )
        
        print(f"  🤖 生成回复: {reply[:80]}...")
        
        # 发送到微信
        # 注意：需要先在微信中打开该聊天窗口
        if self._send_reply(chat_id, reply):
            self.stats["sent"] += 1
            print(f"  ✅ 已发送到微信 [{chat_id}]")
        else:
            print(f"  ❌ 发送失败")
    
    def _send_reply(self, chat_id: str, reply: str) -> bool:
        """
        发送回复到微信
        
        策略：
        1. 尝试打开聊天窗口（使用搜索）
        2. 发送消息
        """
        try:
            # 方案1：假设窗口已打开，直接发送
            success = self.wechat.send_message(reply)
            if success:
                return True
            
            # 方案2：尝试打开聊天窗口
            print(f"  🔍 尝试打开聊天窗口: {chat_id}")
            if self.wechat.open_chat(chat_id):
                time.sleep(0.5)
                return self.wechat.send_message(reply)
            
            return False
            
        except Exception as e:
            print(f"  ❌ 发送异常: {e}")
            return False
    
    def run(self):
        """运行机器人"""
        print("\n" + "=" * 50)
        print("💡 使用说明:")
        print("=" * 50)
        print("1. 确保微信已登录并保持前台")
        print("2. 在微信中打开要自动回复的聊天窗口")
        print("3. 在终端输入消息测试")
        print("   格式: 聊天名称|消息内容")
        print("   示例: 文件传输助手|你好")
        print("4. 机器人会自动回复")
        print("5. 输入 'exit' 退出")
        print("=" * 50 + "\n")
        
        # 启动监听
        try:
            self.watcher.start()
        except KeyboardInterrupt:
            print("\n\n正在停止...")
        finally:
            self.watcher.stop()
            self.reader.close()
        
        # 打印统计
        print(f"\n📊 统计: 收到 {self.stats['received']}, 发送 {self.stats['sent']}")
        print("👋 再见!")


if __name__ == "__main__":
    bot = MacWeChatBot(use_mock=True)
    bot.run()
