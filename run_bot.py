#!/usr/bin/env python3
"""
Mac 微信 RPA 机器人 - 生产环境启动入口
使用新模块化架构 (wechat_rpa) + Kimi LLM 回复
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from wechat_rpa.bot.wechat_bot import WeChatBot
from wechat_rpa.layout.profile import PROFILE_WECHAT_MAC_1760X1280
from utils.llm_client import KimiClient


def main():
    print("=" * 60)
    print("🤖 Mac 微信 RPA 机器人 - 生产环境")
    print("=" * 60)
    print("配置:")
    print("  • 布局: wechat_mac_4.1.8_1760x1280")
    print("  • LLM:  Kimi (kimi-for-coding)")
    print("  • 策略: 群聊直接回复（无需 @）")
    print("  • 轮询: 每 5 秒感知一次")
    print("=" * 60)
    print("按 Ctrl+C 停止\n")

    llm = KimiClient()
    bot = WeChatBot(
        profile=PROFILE_WECHAT_MAC_1760X1280,
        llm_client=llm,
    )

    try:
        bot.run_auto(interval=5.0)
    except KeyboardInterrupt:
        print("\n👋 收到中断信号，正在保存状态并停止...")
        bot.save_sessions()
        bot.running = False
        sys.exit(0)


if __name__ == "__main__":
    main()
