#!/bin/bash
# 启动基于 Quartz 的全自动微信机器人

cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════════"
echo "🤖 微信全自动机器人 (Quartz API 版)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 检查微信
if ! pgrep WeChat > /dev/null; then
    echo "⚠️  微信未运行，正在启动..."
    open -a WeChat
    sleep 5
fi

echo "✅ 微信已运行"
echo ""

# 确保微信在前台
osascript -e 'tell application "WeChat" to activate' 2>/dev/null
echo "✅ 已聚焦微信"
echo ""

echo "⚠️  重要提示："
echo "1. 请确保微信窗口可见"
echo "2. 打开要自动回复的聊天窗口"
echo "3. 按 Ctrl+C 停止机器人"
echo ""

read -p "按回车键开始..."

python3 core/auto_bot_quartz.py
