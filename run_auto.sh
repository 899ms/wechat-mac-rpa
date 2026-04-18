#!/bin/bash
# Mac 微信全自动 RPA 启动脚本

cd "$(dirname "$0")"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🤖 Mac 微信全自动 RPA 机器人${NC}"
echo "============================"

# 1. 检查 SIP
echo -e "\n${YELLOW}1. 检查 SIP 状态...${NC}"
SIP_STATUS=$(csrutil status 2>&1)
if [[ $SIP_STATUS == *"enabled"* ]]; then
    echo -e "${RED}❌ SIP 未关闭${NC}"
    echo "请先关闭 SIP："
    echo "  1. 重启电脑，按住 Cmd + R 进入恢复模式"
    echo "  2. 打开终端，执行: csrutil disable"
    echo "  3. 重启电脑"
    exit 1
else
    echo -e "${GREEN}✅ SIP 已关闭${NC}"
fi

# 2. 检查依赖
echo -e "\n${YELLOW}2. 检查依赖...${NC}"
if ! command -v sqlcipher &> /dev/null; then
    echo "安装 sqlcipher..."
    brew install sqlcipher
fi
echo -e "${GREEN}✅ 依赖检查完成${NC}"

# 3. 检查配置
echo -e "\n${YELLOW}3. 检查配置...${NC}"
if ! grep -q "YOUR_DB_KEY_HERE" config/config.yaml; then
    echo -e "${GREEN}✅ 配置文件已设置${NC}"
else
    echo -e "${RED}❌ 请先配置数据库密钥${NC}"
    echo "编辑 config/config.yaml，设置 db_key"
    exit 1
fi

# 4. 检查微信
echo -e "\n${YELLOW}4. 检查微信...${NC}"
if pgrep -x "WeChat" > /dev/null; then
    echo -e "${GREEN}✅ 微信正在运行${NC}"
else
    echo -e "${RED}❌ 微信未运行${NC}"
    echo "请先启动微信并登录"
    exit 1
fi

# 5. 启动机器人
echo -e "\n${GREEN}🚀 启动全自动机器人...${NC}"
echo "按 Ctrl+C 停止"
echo "============================\n"

python3 core/auto_bot.py
