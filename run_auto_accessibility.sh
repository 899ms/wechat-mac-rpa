#!/bin/bash
# 启动基于 Accessibility API 的全自动微信机器人

cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════════"
echo "🤖 微信全自动机器人 (Accessibility API 版)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 检查微信是否运行
if ! pgrep WeChat > /dev/null; then
    echo "⚠️  微信未运行，正在启动..."
    open -a WeChat
    sleep 5
fi

echo "✅ 微信已运行"
echo ""

# 检查辅助功能权限
echo "检查辅助功能权限..."
# 尝试执行一个需要辅助功能的命令
if ! osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' 2>/dev/null; then
    echo ""
    echo "⚠️  需要授权辅助功能！"
    echo ""
    echo "请按以下步骤操作："
    echo "1. 打开「系统设置」→「隐私与安全」→「辅助功能」"
    echo "2. 点击「+」添加终端程序 (Terminal/iTerm)"
    echo "3. 勾选终端程序"
    echo "4. 返回终端，重新运行此脚本"
    echo ""
    # 打开设置页面
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    exit 1
fi

echo "✅ 辅助功能已授权"
echo ""

# 启动机器人
echo "启动机器人..."
echo ""
python3 core/auto_bot_accessibility.py
