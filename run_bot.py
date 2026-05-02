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

# 加载 .env 文件中的环境变量
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

from wechat_rpa.bot.wechat_bot import WeChatBot
from wechat_rpa.layout.profile import PROFILE_WECHAT_MAC_1760X1280
from wechat_rpa.perception.smart_pipeline import SmartPerceptionPipeline
from utils.qwen_client import QwenClient


def _create_perception(profile):
    """创建感知层：优先使用 SmartPerceptionPipeline（本地预判 + API 兜底），
    环境变量 USE_MULTIMODAL_OCR=false 时回退到原生 VisionPipeline。
    环境变量 ALWAYS_USE_API=true 时禁用本地预判，每次 tick 都调用 API。
    """
    use_smart = os.environ.get("USE_MULTIMODAL_OCR", "true").lower() in ("1", "true", "yes")
    always_api = os.environ.get("ALWAYS_USE_API", "false").lower() in ("1", "true", "yes")
    if use_smart:
        if always_api:
            print("  • 感知层: SmartPerceptionPipeline (激进模式: 每次 tick 都走 API)")
        else:
            print("  • 感知层: SmartPerceptionPipeline (本地预判 + qwen3.5-flash API 兜底)")
        try:
            return SmartPerceptionPipeline(profile, always_use_api=always_api)
        except Exception as e:
            print(f"  ⚠️ SmartPerceptionPipeline 初始化失败: {e}")
            print("  • 回退到 VisionPipeline")
            from wechat_rpa.perception.vision_pipeline import VisionPipeline
            return VisionPipeline(profile)
    else:
        print("  • 感知层: VisionPipeline (纯本地 OCR)")
        from wechat_rpa.perception.vision_pipeline import VisionPipeline
        return VisionPipeline(profile)


class SingleInstanceLock:
    """基于 fcntl 文件锁的单例模式，确保只有一个 Bot 进程运行。"""

    def __init__(self, pid_file: str = ""):
        # 使用绝对路径，防止从不同工作目录启动时创建多个锁文件
        if not pid_file:
            pid_file = str(Path(__file__).parent / "bot.pid")
        self.pid_file = pid_file
        self.fd = None

    def __enter__(self):
        # 先尝试非破坏性地读取旧 PID（用于错误提示）
        old_pid = ""
        try:
            with open(self.pid_file, "r") as f:
                old_pid = f.read().strip()
        except Exception:
            pass

        # 用 r+ 模式打开，避免截断文件；不存在则创建
        try:
            self.fd = open(self.pid_file, "r+")
        except FileNotFoundError:
            self.fd = open(self.pid_file, "w+")

        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            self.fd.close()
            print(f"❌ Bot 已在运行 (PID {old_pid or 'unknown'})，请勿重复启动")
            sys.exit(1)

        self.fd.seek(0)
        self.fd.truncate()
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
        print("  • LLM:  Qwen (qwen3.6-flash)")
        print("  • 策略: 群聊直接回复（无需 @）")
        interval = 10.0 if os.environ.get("ALWAYS_USE_API", "false").lower() in ("1", "true", "yes") else 5.0
        print(f"  • 轮询: 每 {interval:.0f} 秒感知一次")
        print("=" * 60)
        print("按 Ctrl+C 停止\n")

        llm = QwenClient()
        perception = _create_perception(PROFILE_WECHAT_MAC_1760X1280)
        bot = WeChatBot(
            profile=PROFILE_WECHAT_MAC_1760X1280,
            llm_client=llm,
            perception=perception,
        )

        try:
            bot.run_auto(interval=interval)
        except KeyboardInterrupt:
            print("\n👋 收到中断信号，正在保存状态并停止...")
            bot.save_sessions()
            bot.running = False
            sys.exit(0)


if __name__ == "__main__":
    main()
