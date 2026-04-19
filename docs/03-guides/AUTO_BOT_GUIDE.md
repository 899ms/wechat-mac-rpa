# Mac 微信全自动 RPA 完整指南

> ⚠️ **重要警告：本文档描述的数据库解密方案已废弃**
> 
> 当前项目已全面迁移至 **Vision OCR 视觉识别方案**，无需关闭 SIP、无需获取 db_key。
> 
> **推荐快速入口**：
> - 推荐方案：`~~已删除~~ 原: python3 core/auto_bot_vision_ocr_v3.py`
> - 架构文档：`ARCHITECTURE.md`
> - 解决方案：`SOLUTIONS.md`
> 
> 保留本文档仅供历史参考，请勿按本文档操作关闭 SIP 或配置数据库解密。

## 🎯 功能特性

- ✅ **FSEvents 文件监听** - 实时监控微信数据库变化
- ✅ **自动解密** - SQLCipher 解密微信数据库  
- ✅ **智能回复** - Kimi LLM 生成回复
- ✅ **自动发送** - AppleScript 模拟键盘发送
- ✅ **多轮对话** - 上下文记忆
- ✅ **免打扰时段** - 夜间自动静音

## 📋 前置要求

### 1. 系统要求
- macOS 10.15+ (Intel/Apple Silicon)
- 关闭 SIP (系统完整性保护)
- 已登录微信 Mac 版

### 2. 安装依赖
```bash
brew install sqlcipher openssl sqlite3
pip3 install openai
```

### 3. 关闭 SIP
```bash
# 重启进入恢复模式 (Cmd + R)
csrutil disable
reboot

# 验证
csrutil status  # 应显示 disabled
```

## 🚀 快速开始（已废弃，请勿执行）

> ⚠️ 以下步骤属于旧版数据库解密方案，已被废弃。如需使用当前推荐的 Vision OCR 方案，请直接运行 `~~已删除~~ 原: python3 core/auto_bot_vision_ocr_v3.py`。

### 第一步：运行配置向导
```bash
cd /Users/yihanwang/wechat-mac-rpa
python3 setup_auto.py
```

### 第二步：获取数据库密钥
```bash
# 方法1: 使用 wechat-dump
cd ~/wechat-tools/wechat-dump
python3 decrypt.py

# 方法2: 查看 GET_DB_KEY.md 其他方法
```

### 第三步：配置密钥
```bash
# 编辑配置文件
nano config/config.yaml

# 修改 db_key 字段
db_key: "你的32位十六进制密钥"
```

### 第四步：启动机器人
```bash
./run_auto.sh
```

## 📁 项目结构

```
wechat-mac-rpa/
├── config/
│   └── config.yaml           # 配置文件
├── core/
│   ├── auto_bot.py          # 全自动机器人
│   ├── bot_engine.py        # 机器人引擎
│   ├── db_watcher.py        # FSEvents 监听
│   └── message_reader.py    # 消息读取
├── utils/
│   ├── llm_client.py        # Kimi 客户端
│   └── accessibility.py     # Accessibility API
├── db_decrypted/            # 解密后的数据库
├── setup_auto.py            # 配置向导
├── run_auto.sh              # 启动脚本
└── GET_DB_KEY.md            # 密钥获取指南
```

## ⚙️ 配置说明

### config.yaml
```yaml
wechat:
  db_key: "密钥"
  
watcher:
  poll_interval: 3.0          # 轮询间隔（秒）
  whitelist_chats: []         # 白名单（空则监控所有）
  blacklist_chats: []         # 黑名单

llm:
  system_prompt: "..."        # 系统提示词

rules:
  reply_self: false           # 是否回复自己
  min_interval: 5             # 最小回复间隔
  quiet_hours:                # 免打扰时段
    start: "23:00"
    end: "08:00"
```

## 🔒 安全提示

1. **关闭 SIP 有风险**
   - 降低系统安全性
   - 建议仅在开发/测试环境使用
   - 完成后可重新开启

2. **数据库密钥**
   - 相当于微信密码，妥善保管
   - 不要提交到 Git
   - 定期更换

3. **微信账号**
   - 避免高频发送
   - 建议间隔 3-5 秒
   - 不要用于营销/广告

## 🐛 故障排除

### 问题1: 提示 "file is not a database"
**原因**: db_key 不正确
**解决**: 重新获取正确的密钥

### 问题2: "osascript 不允许发送按键"
**原因**: 没有辅助功能权限
**解决**: 系统设置 → 隐私与安全 → 辅助功能 → 添加终端

### 问题3: 无法读取数据库
**原因**: SIP 未关闭或数据库路径错误
**解决**: 
```bash
# 检查 SIP
csrutil status

# 查找数据库
find ~/Library/Containers/com.tencent.xinWeChat -name "msg_*.db"
```

### 问题4: Kimi API 调用失败
**原因**: API Key 无效或过期
**解决**: 检查 .env 文件中的 API Key

## 📝 更新日志

### v2.0 (当前)
- ✅ FSEvents 文件监听
- ✅ SQLCipher 数据库解密
- ✅ Kimi LLM 集成
- ✅ AppleScript 消息发送

## 📚 参考链接

- [wechat-dump](https://github.com/0xHJK/wechat-dump)
- [chatlog-bot](https://github.com/rockswang/chatlog-bot)
- [wemac](https://github.com/x5iu/wemac)

## ⚠️ 免责声明

本项目仅供学习和技术研究使用，请勿用于：
- 批量发送营销广告
- 骚扰他人
- 违反微信使用规范的行为

使用本项目产生的任何后果由用户自行承担。
