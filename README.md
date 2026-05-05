# WeChat Mac RPA

> 基于多模态视觉感知与 LLM 认知中枢的 macOS 微信自动化框架

```
CV 视觉输入  →  LLM 推理  →  系统自动化输出
     感知         认知           执行
```

---

## 背景

微信官方不提供 Bot API，现有方案大致两类：一类是逆向工程（协议破解、Hook、Pad 协议），与微信做持续对抗，封号风险高、维护成本不可控；另一类是传统 RPA/OCR，靠模板匹配和关键词触发，版本绑定严重，无法理解语义上下文。

本项目走第三条路：**不做逆向，不碰协议，把微信当作一个黑盒 GUI 应用来操作**。用计算机视觉"看"屏幕，用大语言模型理解对话，用系统级自动化"操作"界面。微信更新 UI 只是换了一套视觉输入，不需要追着协议跑。

---

## 核心设计

### 双模型路由：快响应与深分析分离

单一模型无法同时满足"秒回闲聊"和"深度推理"。系统内置动态路由：

| 场景 | 模型 | 能力 |
|------|------|------|
| 日常对话 | deepseek-v4-flash (DashScope) | Tool Calling、低延迟、低成本 |
| 复杂任务 | Hermes Agent (本地 8642 端口) | 长上下文、深度推理、Skill 自主加载 |

路由基于消息语义自动触发——默认走 deepseek，当内容匹配特定 Skill（深度分析、投研报告等）时自动切换到 Hermes，两者拥有独立的 system prompt 和工具体系。

### SmartPerceptionPipeline：92.6% 的 tick 无需调用 API

传统方案要么全走本地 OCR（准确率 ~60%），要么全走云端 API（成本高、延迟大）。我们设计了两级感知：

```
截图 → 像素差异 + 局部哈希判断
         │
         ├── 无变化 → 复用上轮结果，零 API 调用
         │
         └── 有变化 → 本地 OCR 提取聊天列表 + qwen3.6-flash 识别消息内容
```

- **第一级**：本地预判。基于像素差异判断截图是否有实质变化。
- **第二级**：云端兜底。消息内容交给多模态模型识别，群聊昵称、emoji、换行格式准确率从 ~60% 提升到 ~83%。

基于 69 张连续截图的评测：**92.6% 的 tick 无需调用 API**。

### Agent 运行时：不止于"调用 LLM API"

ReplyGenerator 是一个完整的 Agent 运行时，而非简单的 API 封装：

**Func Tool 体系**：
- `web_search`：360 搜索，通过 `data-mdurl` 提取真实 URL（规避加密跳转链）
- `browse_url`：网页正文提取，含微信公众号文章特殊解析
- `get_current_time` / `get_weather` / `stock_query` / `search_memory`

**Skill 路由**：基于消息语义匹配外挂 Markdown Skill 文件，动态注入 prompt，无需改代码即可扩展能力。

**Tool Calling 控制**：支持多轮工具调用（如搜索后浏览），总工具时间上限 20 秒，超时强制切纯文本回复；空 reply 自动 retry（最多 3 次 attempt）。

### 记忆系统：短期缓存 + 长期 Wiki

**Session Memory（跨 tick 短期）**：
- 缓存工具结果，避免重复搜索。TTL 策略：`web_search` 5min / `stock_query` 1min / `get_weather` 30min / `search_memory` 10min
- 过期缓存保留 2 倍 TTL，作为"近期参考"供 LLM 判断信息时效性

**Memory Engine（长期）**：
- 每个用户/群聊拥有独立的 LLM Wiki（Markdown），异步后台线程基于对话记录自动更新
- 支持外挂 Overrides：事实纠正、别名映射、群聊专用规则
- 更新规则：增量修改、时间敏感信息带日期、7 天动态归档、冲突覆盖

### 去重：三层防御 + 回声消除

微信消息去重是 RPA 的核心难题——同一条消息可能在多个 tick 中被重复识别，Bot 自己的回复也会被 OCR 识别为"新消息"。

**第一层：LCS 序列对齐**。在历史消息序列中寻找 tick 的最长公共子序列，时间复杂度 O(m×n)，历史窗口控制在 50-150 条。

**第二层：精确指纹**。基于 `chat_name|标准化 sender|内容 hash` 精确匹配。sender 标准化消除 OCR 昵称漂移：私聊时把"对方"/"[未知]"统一替换为 chat_name。

**第三层：模糊兜底**。文字消息用 difflib.SequenceMatcher，按长度动态调整阈值（短消息更严格）；图片/表情用 2-gram Jaccard（阈值 0.08，应对 qwen 描述不稳定）。

**回声检测**：Bot 发送后记录内容 + 时间 + 估计 Y 坐标。下轮识别时，10 秒窗口内 + Y 坐标接近 + 文本包含关系 → 判定为回声丢弃。

---

## 架构

严格的分层架构（L1-L5），每层只向下依赖，禁止跨层调用。

```
┌─────────────────────────────────────────────────────────────┐
│  L5: Bot Orchestrator                                       │
│  wechat_rpa/bot/wechat_bot.py                               │
│  主循环：perceive → session → policy → generate → action   │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│  L4: Session │    │  L4: Reply      │    │  L4: Action  │
│  会话/去重   │    │  回复决策/生成  │    │  执行发送    │
│  global_store│    │  policy+generator│   │  sender+clicker│
└──────────────┘    └─────────────────┘    └──────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│  L3.5: SmartPerceptionPipeline                              │
│  智能感知：本地预判 + API 兜底，对上层隐藏视觉实现细节      │
└─────────────────────────────────────────────────────────────┘
        │
        ├──► L3: Layout Parser  ──► L2: OCR / Capture
        └──► L3: Message Extractor
```

**依赖规则**：
- Domain (L1) 不依赖任何其他层
- Capture/OCR/LayoutProfile (L2) 只依赖 L1
- Message/Layout (L3) 只依赖 L1-L2
- SmartPerception (L3.5) 可依赖 L1-L3，但**对 L4-L5 隐藏内部细节**
- Session/Reply/Action (L4) 只消费 `PerceptionResult` 和 `ChatMessage`
- Bot (L5) 只依赖 L1、L3.5、L4

**防越界原则**：去重是 L4 的职责，感知层禁止做状态管理；回复决策是 L4 的职责，Bot 层禁止直接操作 UI。

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

Bot 启动后进入 tick 循环（默认 5 秒间隔）：截图 → 感知 → 去重 → 决策 → 生成 → 发送 → 持久化。

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
│   ├── session/global_store.py        # L4: 全局消息存储 + 三层去重
│   ├── reply/
│   │   ├── policy.py                  # L4: 回复决策
│   │   ├── generator.py               # L4: 回复生成（Tool Calling + Skill 路由 + 双模型分流）
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
│   ├── debug/                         # tick 级 debug JSON（运行时可观测）
│   ├── memory/wiki/                   # 用户/群聊/话题 wiki
│   └── screenshots/                   # 截图存档
└── run_bot.py                         # 生产环境入口
```

---

## 更多文档

- [架构设计](docs/02-architecture/ARCHITECTURE.md) — 分层架构、模块边界、依赖规则
- [模块索引](docs/02-architecture/MODULE_INDEX.md) — 改代码前先看这个
- [踩坑记录](docs/04-troubleshooting/LESSONS_LEARNED.md) — 避免重复踩坑
- [Tick 排查指南](docs/04-troubleshooting/TICK_INVESTIGATION_GUIDE.md) — 消息未回复时如何定位
- [日志设计](docs/03-guides/LOGGING_DESIGN.md) — debug JSON 结构和可观测性

---

## 免责声明

本项目仅用于个人学习和技术研究。使用自动化工具操作微信可能违反微信用户协议，请自行评估风险。
