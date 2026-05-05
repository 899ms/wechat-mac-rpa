# WeChat Mac RPA

基于多模态视觉感知与 LLM 推理的 macOS 微信自动化框架。

```
感知 → 思考 → 行动
```

---

## 背景

微信官方不提供 Bot API，现有方案要么走逆向工程（协议破解、Hook、Pad 协议），与微信持续对抗，封号风险高、维护成本不可控；要么走传统 RPA/OCR，靠模板匹配和关键词触发，版本绑定严重，无法理解语义上下文。

本项目把微信当作一个黑盒 GUI 应用，用计算机视觉读取界面，用大语言模型理解对话，用系统级自动化操作界面。微信更新 UI 只是换了一套视觉输入，不需要追着协议跑。

---

## 架构

系统以固定周期运行 tick 循环，整体按职责分为五层：

```
L5  Bot Orchestrator
     主循环编排：感知 → 会话 → 决策 → 生成 → 行动

L4  Session / Reply / Action
     会话管理、回复决策与生成、消息发送

L3.5 SmartPerceptionPipeline
     本地预判 + API 兜底，对上层隐藏视觉实现细节

L3  Layout Parser / Message Extractor
L2  OCR / Capture / LayoutProfile
L1  Domain Models
```

每层只向下依赖，上层不感知下层的具体实现。Bot 层只消费 `PerceptionResult` 和 `ChatMessage`，不直接接触 OCR、截图或布局解析。

---

### 感知层

传统 OCR 方案要么全走本地（准确率有限），要么全走云端 API（成本高、延迟大）。我们设计了两级感知管道：

第一级基于像素差异和局部哈希判断截图是否有实质变化，无变化时直接复用上轮结果，零 API 调用。第二级将消息内容交给多模态模型识别，群聊昵称、emoji、换行格式的准确率显著提升。评测显示绝大部分 tick 无需调用 API。

### 思考层

这是系统的认知中枢，也是核心差异化所在。

**双模型路由**：单一模型无法同时满足"秒回闲聊"和"深度推理"。日常对话走 deepseek-v4-flash（低延迟、Tool Calling）；当消息语义匹配特定 Skill（深度分析、投研报告等）时自动切换到 Hermes Agent（长上下文、深度推理）。两者拥有独立的 system prompt 和工具体系。

**Agent 运行时**：ReplyGenerator 并非简单的 API 封装，而是一个完整的 Agent 运行时。支持多轮工具调用、超时保护、空回复自动重试。工具体系包括网络搜索、网页浏览、天气查询、股票查询、本地记忆检索等。Skill 是外挂的 Markdown 文件，基于语义匹配动态注入 prompt，无需改代码即可扩展能力。

**记忆系统**：Session Memory 跨 tick 缓存工具结果，避免重复搜索，带 TTL 失效策略。Memory Engine 为每个用户/群聊维护独立的 LLM Wiki，由后台异步线程基于对话记录自动更新，支持外挂 Overrides（事实纠正、别名映射、群聊专用规则）。

### 行动层

消息发送采用剪贴板粘贴方案，规避中文输入法下的乱码问题。支持聊天列表切换、登录恢复（自动检测扫码界面并点击登录按钮）。

---

## 快速开始

### 环境

- macOS 12+（Intel / Apple Silicon）
- 微信 Mac 版（已登录，窗口可见）
- Python 3.10+

### 安装

```bash
cd ~/wechat-mac-rpa
pip install pyobjc numpy scipy pillow python-dotenv requests
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY
```

```env
DASHSCOPE_API_KEY=sk-your-key-here
USE_MULTIMODAL_OCR=true
ALWAYS_USE_API=false
HERMES_BASE_URL=http://127.0.0.1:8642   # 可选，用于复杂任务
```

### 启动

```bash
python3 run_bot.py
```

### 测试

```bash
python3 -m pytest tests/ -q
```

---

## 项目结构

```
wechat-mac-rpa/
├── wechat_rpa/
│   ├── bot/wechat_bot.py              # L5: 主循环编排
│   ├── perception/
│   │   ├── smart_pipeline.py          # L3.5: 智能感知（本地预判 + API 兜底）
│   │   └── vision_pipeline.py         # L3.5: 纯本地 OCR 备用管道
│   ├── layout/
│   │   ├── layout_parser.py           # L3: 布局解析
│   │   └── profile.py                 # L2: 布局配置（多版本/分辨率适配）
│   ├── message/extractor.py           # L3: 消息提取（聚类、sender 判定）
│   ├── session/global_store.py        # L4: 全局消息存储
│   ├── reply/
│   │   ├── policy.py                  # L4: 回复决策
│   │   ├── generator.py               # L4: 回复生成（Agent 运行时 + 双模型分流）
│   │   └── session_memory.py          # L4: 跨 tick 工具缓存
│   ├── action/
│   │   ├── message_sender.py          # L4: 消息发送
│   │   ├── chat_list_clicker.py       # L4: 聊天列表切换
│   │   └── login_recovery.py          # L4: 登录恢复
│   ├── memory/engine.py               # L4: 长期记忆引擎（LLM Wiki + Overrides）
│   ├── tools/                         # Func Tool 体系
│   ├── capture/window_capture.py      # L2: Quartz 窗口枚举 + screencapture
│   ├── ocr/vision_ocr.py              # L2: macOS Vision 框架文字识别
│   ├── models/base.py                 # L1: 领域模型
│   └── llm/openclaw_client.py         # OpenAI-compatible API 客户端
├── tests/                             # 测试套件
├── data/
│   ├── debug/                         # tick 级 debug JSON
│   ├── memory/wiki/                   # 用户/群聊/话题 wiki
│   └── screenshots/                   # 截图存档
└── run_bot.py                         # 生产环境入口
```

---

## 更多文档

- [架构设计](docs/02-architecture/ARCHITECTURE.md)
- [模块索引](docs/02-architecture/MODULE_INDEX.md)
- [踩坑记录](docs/04-troubleshooting/LESSONS_LEARNED.md)
- [Tick 排查指南](docs/04-troubleshooting/TICK_INVESTIGATION_GUIDE.md)
- [日志设计](docs/03-guides/LOGGING_DESIGN.md)

---

## 免责声明

本项目仅用于个人学习和技术研究。使用自动化工具操作微信可能违反微信用户协议，请自行评估风险。
