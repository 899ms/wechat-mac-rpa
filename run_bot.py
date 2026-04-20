#!/usr/bin/env python3
"""
Mac 微信 RPA 机器人 - 生产环境启动入口
使用新模块化架构 (wechat_rpa) + Kimi LLM 回复
"""

import sys
import os
import fcntl
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from wechat_rpa.bot.wechat_bot import WeChatBot
from wechat_rpa.layout.profile import PROFILE_WECHAT_MAC_1760X1280
from utils.llm_client import KimiClient


class SingleInstanceLock:
    """基于 fcntl 文件锁的单例模式，确保只有一个 Bot 进程运行。"""

    def __init__(self, pid_file: str = "bot.pid"):
        self.pid_file = pid_file
        self.fd = None

    def __enter__(self):
        self.fd = open(self.pid_file, "w")
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            try:
                with open(self.pid_file) as f:
                    old_pid = f.read().strip()
            except Exception:
                old_pid = "unknown"
            print(f"❌ Bot 已在运行 (PID {old_pid})，请勿重复启动")
            sys.exit(1)

        self.fd.write(str(os.getpid()))
        self.fd.flush()
        return self

    def __exit__(self, *args):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except (IOError, OSError):
                pass
            self.fd.close()
            try:
                os.remove(self.pid_file)
            except OSError:
                pass


def main():
    with SingleInstanceLock():
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
