#!/bin/bash
# 微信截图并添加测试用例脚本
# 用法: ./capture_and_add_test.sh [测试名称]

cd "$(dirname "$0")"

# 默认测试名称
TEST_NAME="${1:-test_$(date +%m%d_%H%M%S)}"

echo "=================================="
echo "📸 微信截图 + 添加测试用例"
echo "=================================="
echo ""
echo "测试名称: $TEST_NAME"
echo ""
echo "请确保:"
echo "  1. 微信正在运行"
echo "  2. 微信窗口可见"
echo "  3. 已切换到想截图的聊天窗口"
echo ""
echo "5秒后开始截图..."
sleep 5

# 截图
echo "📸 正在截图..."
python3 -c "
import sys
sys.path.insert(0, '.')
from core.auto_bot_vision_ocr_v4 import WeChatVisionOCRBotV4
import shutil

bot = WeChatVisionOCRBotV4()
bot.focus_wechat()
win = bot.capture_wechat()

if win:
    print(f'✅ 截图成功: {win[\"width\"]}x{win[\"height\"]}')
    shutil.copy2(bot.screenshot_path, '/tmp/wechat_new_test.png')
    print('已保存到: /tmp/wechat_new_test.png')
else:
    print('❌ 截图失败')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo "截图失败"
    exit 1
fi

# 添加测试用例
echo ""
echo "📝 添加测试用例..."
python3 tests/add_test_case.py /tmp/wechat_new_test.png --name "$TEST_NAME"

echo ""
echo "=================================="
echo "✅ 完成！"
echo "=================================="
echo ""
echo "运行测试: ./tests/run_tests.sh"
