# Mac 微信 RPA 机器人

基于 **Vision OCR 视觉识别** 的 Mac 微信自动化方案。

> ⚠️ **重要提示**: 本项目严格执行 [测试错误零容忍政策](CODE_OF_CONDUCT.md)。所有识别错误必须在 24 小时内修复。

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

### 方式 1: OCR V3 颜色气泡版（推荐）

通过检测绿色/灰色气泡区分消息，识别最精确。

```bash
cd ~/wechat-mac-rpa
python3 core/auto_bot_vision_ocr_v3.py
```

### 方式 2: OCR V4 稳定版（当前实际运行）

当前线上稳定运行的 monolithic 版本，功能与 V3 类似。

```bash
cd ~/wechat-mac-rpa
python3 core/auto_bot_vision_ocr_v4.py
```

### 方式 3: OCR V2 增强版

支持多对话管理、上下文隔离、@检测。

```bash
python3 core/auto_bot_vision_ocr_v2.py
```

### 方式 4: Accessibility API 版

需要辅助功能权限，界面控制更精确。

```bash
./run_auto_accessibility.sh
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
├── core/                            # 当前可直接运行的 monolithic 版本
│   ├── auto_bot_vision_ocr_v4.py    ⭐ 当前线上稳定版（monolithic）
│   ├── auto_bot_vision_ocr_v3.py    OCR V3 颜色气泡版
│   ├── auto_bot_vision_ocr_v2.py    OCR V2 增强版
│   ├── auto_bot_accessibility.py    ⌨️ Accessibility API 版
│   └── wechat_layout_analyzer.py    📐 布局分析器
├── wechat_rpa/                      # 当前模块化实现（与 ARCHITECTURE.md 目标架构存在差异）
│   ├── capture/                     # 截图模块
│   │   └── window_capture.py
│   ├── ocr/                         # OCR 模块
│   │   └── vision_ocr.py
│   ├── parser/                      # 解析模块（当前实际：统一处理布局+消息提取）
│   │   └── wechat_parser.py
│   ├── action/                      # 发送与回复模块（当前实际：策略+生成+发送在同一目录）
│   │   ├── message_sender.py
│   │   └── reply_generator.py
│   ├── bot/                         # 主循环编排
│   │   └── wechat_bot.py
│   ├── storage/                     # 聊天记录存储
│   │   ├── message_store.py         # 旧版存储（当前 V4 仍在使用）
│   │   └── chat_history.py          # 新版 JSONL 存储（目标架构设计）
│   ├── logging/                     # 可观测性
│   │   └── bot_logger.py
│   ├── utils/                       # LLM 客户端
│   │   └── llm_client.py
│   └── tests/                       # 模块测试
│       ├── test_modules.py
│       └── fixtures/
├── tests/                           # 顶层测试目录（OCR V4 回归测试）
│   ├── test_ocr_v4.py
│   ├── fixtures/
│   └── ...
├── utils/
│   ├── llm_client.py                🧠 Kimi LLM 客户端
│   └── accessibility.py             ⌨️ Accessibility 工具
├── scripts/
│   └── view_ocr_history.py          📜 查看识别历史
├── examples/                        📚 示例代码
├── run_simple.py                    🚀 简化版启动
├── run_auto_accessibility.sh        🚀 Accessibility 版启动
└── run_auto_quartz.sh               🚀 Quartz 版启动
```

---

## 🔧 实用命令

### 查看 OCR 识别历史
```bash
python3 scripts/view_ocr_history.py
```

### 导出识别日志
```bash
python3 scripts/view_ocr_history.py export
```

### 布局分析（调试）
```bash
python3 core/wechat_layout_analyzer.py
```

---

## 📊 版本对比

| 功能 | V4 稳定版 | V3 颜色气泡 | V2 增强版 | Accessibility |
|------|----------|------------|-----------|---------------|
| 全自动监听 | ✅ | ✅ | ✅ | ✅ |
| 多对话管理 | ✅ | ✅ | ✅ | ✅ |
| 发言人识别 | ✅ 精确 | ✅ 精确 | ⚠️ 有限 | ✅ |
| @检测 | ✅ | ✅ | ✅ | - |
| 无需 SIP | ✅ | ✅ | ✅ | ✅ |
| 无需 db_key | ✅ | ✅ | ✅ | ✅ |
| 需要辅助功能 | ❌ | ❌ | ❌ | ✅ |

---

## 🎨 OCR V3 颜色气泡原理

```
微信Mac版界面
┌─────────────────────────────────────────────┐
│ 微信Mac版界面                                │
├────────────┬────────────────────────────────┤
│ 左侧聊天列表 │ 右侧当前聊天内容               │
│ (x<300)    │ (x>=300)                       │
│            │                                │
│ ○ 头像     │  [群名] - 顶部标题栏           │
│   昵称     │  ──────────────────            │
│   预览     │  [昵称]                        │
│            │  ┌──────────────┐  ← 灰色气泡  │
│            │  │ 消息内容      │    对方消息  │
│            │  └──────────────┘              │
│            │  ┌──────────────┐  ← 绿色气泡  │
│            │  │ 消息内容      │    自己消息  │
│            │  │ 多行文本...   │    RGB(176,  │
│            │  └──────────────┘    240, 167) │
└────────────┴────────────────────────────────┘
```

**颜色特征**:
- 自己消息: `RGB(176, 240, 167)` 绿色
- 对方消息: `RGB(238, 238, 240)` 灰色/白色
- 背景: `RGB(250, 250, 250)` 白色

---

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

- [架构设计](ARCHITECTURE.md) — AI 开发者和维护者必读
- [AI 快速上手](AI_QUICKSTART.md) — 第一次接触本项目从这里开始
- [模块索引](MODULE_INDEX.md) — 不知道改哪个文件时先查这个
- [日志设计](LOGGING_DESIGN.md) — 运行时日志与聊天记录持久化
- [踩坑记录](LESSONS_LEARNED.md) — 避免重复踩坑
- [解决方案汇总](SOLUTIONS.md)
- [项目进度](PROJECT_STATUS.md)
- [V2 功能说明](V2_FEATURES.md)

---

## ❌ 废弃方案

### 数据库解密方案（不再维护）
```
原方案: 解密微信 SQLite 数据库
状态: 已废弃
原因: 需要关闭 SIP + 获取 db_key
替代: Vision OCR 视觉识别
```

---

**推荐使用 OCR V3 颜色气泡版！**
