#!/usr/bin/env python3
"""
Mac 微信全自动 RPA 机器人 - 启动入口

功能：
- FSEvents 监听微信数据库
- Kimi LLM 生成回复
- Accessibility API 发送消息
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from core.bot_engine import MacWeChatBot


def main():
    """主入口"""
    print("""
╔══════════════════════════════════════════════════╗
║     🤖 Mac 微信全自动 RPA 机器人 v1.0            ║
╠══════════════════════════════════════════════════╣
║  技术栈:                                         ║
║    • FSEvents 文件监听                           ║
║    • Kimi LLM 大模型                             ║
║    • Accessibility API 发送消息                   ║
╚══════════════════════════════════════════════════╝
    """)
    
    # 检查依赖
    try:
        import pyautogui
        import pyperclip
        import openai
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请安装: pip install pyautogui pyperclip openai watchdog")
        sys.exit(1)
    
    # 启动机器人
    bot = MacWeChatBot(use_mock=True)
    bot.run()


if __name__ == "__main__":
    main()
