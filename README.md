# Mac 微信 RPA 机器人

基于 **Vision OCR 视觉识别** 的 Mac 微信自动化方案。

> ⚠️ **重要提示**: 本项目严格执行 [测试错误零容忍政策](docs/05-meta/CODE_OF_CONDUCT.md)。所有识别错误必须在 24 小时内修复。

---

## 🎯 方案概述

```
消息接收: Vision OCR 识别微信界面截图
消息发送: AppleScript + System Events
大模型: Kimi / OpenAI
```

**核心优势**:
- ✅ 无需关闭 SIP
- ✅ 无需获取 db_key
- ✅ 不依赖微信数据库
- ✅ 更安全、更稳定

---

## 📋 前置要求

1. Mac 电脑（Intel/Apple Silicon 均可）
2. 微信 Mac 版（已登录，窗口可见）
3. Python 3.8+
4. 依赖包

### 安装依赖

```bash
pip install pyobjc numpy scipy pillow python-dotenv
```

---

## 🚀 快速开始

### 启动机器人

当前唯一维护的版本，基于 L1-L5 分层架构。

```bash
cd ~/wechat-mac-rpa
python3 -m wechat_rpa.bot.wechat_bot
```

或运行集成测试：

```bash
python3 tests/test_integration.py
```

---

## 🛠️ 配置

### API Key 配置

编辑 `~/omni-bot-sdk-oss/.env`:

```env
KIMI_API_KEY=your_api_key_here
```

### 辅助功能权限（仅 Accessibility 方案需要）

```
系统设置 → 隐私与安全 → 辅助功能
→ 添加并勾选终端程序
```

---

## 📁 项目结构

```
wechat-mac-rpa/
├── wechat_rpa/                      # 模块化架构实现（L1-L5）
│   ├── bot/                         # L5: 主循环编排
│   │   └── wechat_bot.py            ⭐ 唯一入口
│   ├── perception/                  # L3.5: 视觉感知管道
│   │   └── vision_pipeline.py
│   ├── layout/                      # L3: 布局解析
│   │   └── layout_parser.py
│   ├── session/                     # L4: 会话与去重
│   │   └── chat_session.py
│   ├── reply/                       # L4: 回复决策与生成
│   │   ├── policy.py
│   │   └── generator.py
│   ├── action/                      # L4: 消息发送
│   │   ├── message_sender.py
│   │   └── chat_list_clicker.py
│   ├── storage/                     # 聊天记录存储
│   │   └── message_store.py
│   ├── logging/                     # 可观测性
│   │   └── bot_logger.py
│   └── utils/                       # 工具类
│       └── llm_client.py
├── tests/                           # 测试套件
│   ├── test_integration.py
│   └── fixtures/
├── scripts/
│   └── view_ocr_history.py          # 查看识别历史
└── data/                            # 数据目录
    ├── screenshots/                 # 截图存档
    └── logs/                        # 运行日志
```

---

## 🔧 实用命令

### 启动机器人
```bash
cd ~/wechat-mac-rpa
python3 -m wechat_rpa.bot.wechat_bot
```

### 运行测试
```bash
python3 tests/test_integration.py
```

### 查看 OCR 识别历史
```bash
python3 scripts/view_ocr_history.py
```

### 导出识别日志
```bash
python3 scripts/view_ocr_history.py export
```

**入口: `python3 -m wechat_rpa.bot.wechat_bot`**

## ⚠️ 注意事项

1. **微信窗口需要可见**
   - OCR 需要截取微信窗口
   - 窗口不能被其他窗口完全遮挡

2. **避免高频发送**
   - 建议间隔 3-5 秒
   - 防止被微信限制

3. **OCR 精度**
   - 小字体昵称可能识别不准
   - 复杂背景可能影响识别

---

## 📚 更多文档

- [架构设计](docs/02-architecture/ARCHITECTURE.md) — AI 开发者和维护者必读
- [AI 快速上手](docs/01-quickstart/AI_QUICKSTART.md) — 第一次接触本项目从这里开始
- [模块索引](docs/02-architecture/MODULE_INDEX.md) — 不知道改哪个文件时先查这个
- [日志设计](docs/03-guides/LOGGING_DESIGN.md) — 运行时日志与聊天记录持久化
- [踩坑记录](docs/04-troubleshooting/LESSONS_LEARNED.md) — 避免重复踩坑
- [解决方案汇总](docs/04-troubleshooting/SOLUTIONS.md)
- [项目进度](docs/03-guides/PROJECT_STATUS.md)

---

## ❌ 废弃方案

### 数据库解密方案（不再维护）
```
原方案: 解密微信 SQLite 数据库
状态: 已废弃
原因: 需要关闭 SIP + 获取 db_key
替代: Vision OCR 视觉识别
```

### Monolithic 版本（已删除）
```
原方案: core/auto_bot_vision_ocr_v2/v3/v4.py
状态: 已删除
原因: 代码耦合，难以维护
替代: wechat_rpa/ 模块化架构
```

---


