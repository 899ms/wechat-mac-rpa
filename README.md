# WeChat Mac RPA — 基于视觉感知的微信自动化机器人

> **纯视觉驱动 · 零侵入 · 分层架构 · 双模型路由**

```
SEE  →  THINK  →  ACT
截图    推理      操作
```

---

## 一、为什么做这个项目

微信官方不提供 Bot API，且对自动化持明确反对态度。在"无官方接口"的约束下，业界形成了三条技术路线，各有其天花板：

### 路线一：逆向工程

| 子路线 | 原理 | 核心缺点 |
|--------|------|---------|
| **协议破解** | 分析微信客户端与服务器的通信协议，实现独立客户端 | 协议频繁升级，一次更新可能全量失效；法律风险高；账号封禁概率极高 |
| **网页版/PC Hook** | 注入 DLL 或 Hook 系统 API 拦截消息 | 微信网页版功能被大幅削减，PC Hook 触发风控后账号直接限制登录 |
| **Pad 协议** | 模拟平板客户端协议 | 需要购买商用协议服务，按号收费，成本不可控；同样面临协议升级和封号风险 |

**共同困境**：与微信做"军备竞赛"。每次微信更新，逆向方案需要数天到数周的修复周期，且封号是悬在头上的达摩克利斯之剑。

### 路线二：传统 RPA / 纯 OCR

原理：截图 → OCR 识别文字 → 正则匹配关键词 → 触发固定回复模板。

**核心缺点**：
- **版本绑定严重**：微信 UI 微调（按钮位置、字体大小、颜色值）就会导致脚本失效
- **实现复杂度爆炸**：需要为每一种消息类型（文字、图片、语音、引用、@消息、红包、转账）写专门的解析逻辑
- **鲁棒性差**：中文 OCR 在复杂背景、小字体、表情包叠加场景下准确率骤降
- **无法理解语义**：只能做"关键词→固定回复"的机械映射，无法处理上下文和多轮对话

### 本项目的定位

**不做逆向，不做 Hook，不碰协议**。

我们把微信当成一个"黑盒 GUI 应用"，用计算机视觉"看"屏幕，用大语言模型"理解"对话，用系统自动化"操作"界面。微信怎么更新 UI，我们就怎么重新"看"——不需要追着协议跑，也不需要关闭 SIP。

---

## 二、架构设计：SEE → THINK → ACT

项目采用严格的分层架构（L1-L5），每层只向下依赖，禁止跨层调用。

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

## 三、核心技术亮点

### 3.1 SmartPerceptionPipeline：92.6% 的 tick 无需调用 API

传统 OCR 方案要么全走本地（准确率 ~60%），要么全走云端 API（成本高、延迟大）。我们设计了两级感知管道：

```
截图 → 像素差异判断 ──无变化──► 本地 LayoutParser(chat_list) + 空 messages
                    │
                    └──有变化──► 本地 LayoutParser(chat_list) + qwen3.6-flash(messages)
```

- **第一级：本地预判**。基于像素差异 + 局部哈希，判断截图是否有实质性变化。无变化时直接复用上轮结果，零 API 调用。
- **第二级：云端兜底**。有变化时，本地 OCR 提取聊天列表（用于切换聊天），消息内容交给 **qwen3.6-flash** 多模态模型识别。相比传统 OCR，群聊昵称、emoji、换行格式的识别准确率从 ~60% 提升到 ~83%。

基于 69 张连续截图的评测：**92.6% 的 tick 无需调用 API**，既省钱又低延迟。

### 3.2 双模型分流：快思考 vs 深思考

单一模型无法同时满足"秒回闲聊"和"深度分析"的需求。我们实现了动态模型路由：

| 场景 | 模型 | 特点 |
|------|------|------|
| **日常闲聊** | deepseek-v4-flash (via DashScope) | 低延迟、低成本、支持 Tool Calling |
| **复杂任务** | Hermes Agent (本地 8642 端口) | 长上下文、深度推理、支持 Skill 加载 |

**路由策略**：
- 默认走 deepseek，响应快、成本低
- 当消息匹配到特定 Skill（如"深度分析"、"投研报告"）时，自动切到 Hermes
- Hermes 拥有独立的 system prompt 和 skill 体系，不传入 tools，由 Agent 自行决定调用链

### 3.3 自建 Agent：麻雀虽小，五脏俱全

我们的 ReplyGenerator 不是简单的"调用 LLM API"，而是一个完整的 Agent 运行时：

**Func Tool 体系**：
- `web_search`：360 搜索，自动解码跳转链接获取真实 URL
- `browse_url`：提取网页正文（含微信公众号文章特殊解析）
- `get_current_time` / `get_weather`：基础信息工具
- `stock_query`：股票查询
- `search_memory`：查询本地长期记忆 wiki

**Skill 路由**：
- 基于消息内容的语义匹配，动态加载对应的 skill 正文注入 prompt
- Skill 是外挂的 Markdown 文件，无需改代码即可扩展能力
- 复杂 skill 自动路由到 Hermes 深度处理

**Tool Calling 控制**：
- 支持多轮 tool 调用（如先 `web_search` 再 `browse_url`）
- 总工具时间上限 20 秒，超时时强制切到纯文本回复
- 空回复自动 retry（最多 3 次 attempt）

### 3.4 记忆系统：短期缓存 + 长期 Wiki

**Session Memory（短期）**：
- 跨 tick 缓存工具结果，避免重复搜索
- TTL 策略：`web_search` 5min / `stock_query` 1min / `get_weather` 30min / `search_memory` 10min
- 过期缓存保留 2 倍 TTL 时间，作为"近期参考"供 LLM 判断信息时效性

**Memory Engine（长期）**：
- 每个用户/群聊拥有独立的 LLM Wiki（Markdown 格式）
- 异步后台线程，基于对话记录自动更新 wiki
- 支持外挂 Overrides：事实纠正、别名映射、群聊专用规则
- wiki 更新规则：只修改变化部分、时间敏感信息带日期、超过 7 天的动态归档、冲突时新信息覆盖旧信息

### 3.5 去重系统：三层防御

微信消息去重是 RPA 的核心难题——同一条消息可能在多个 tick 中被重复识别，Bot 自己的回复也会被 OCR 识别为"新消息"。

我们设计了三层去重：

**第一层：滑动前缀匹配（LCS 序列对齐）**
- 在历史消息序列中寻找 tick 的最长公共子序列
- 时间复杂度 O(m×n)，实际运行中历史窗口控制在 50-150 条，性能可忽略

**第二层：精确去重（_msg_id）**
- 基于 `chat_name|标准化 sender|内容指纹` 的精确匹配
- sender 标准化：私聊时把"对方"/"[未知]"统一替换为 chat_name，消除 OCR 昵称识别不稳定带来的漂移

**第三层：模糊去重（_is_fuzzy_duplicate）**
- 文字消息：difflib.SequenceMatcher，按消息长度动态调整阈值（短消息更严格）
- 图片/表情：2-gram Jaccard，阈值 0.08（极低，应对 qwen 描述不稳定）
- 只对比最近 lookback 条历史，避免遍历全部

**回声检测**：
- Bot 发送消息后记录内容 + 时间 + 估计 Y 坐标
- 下轮识别时，10 秒时间窗口内 + Y 坐标接近 + 文本包含关系 → 判定为回声，直接丢弃

---

## 四、快速开始

### 环境要求

- macOS 12+（Intel / Apple Silicon）
- 微信 Mac 版（已登录，窗口可见）
- Python 3.10+

### 安装依赖

```bash
cd ~/wechat-mac-rpa
pip install pyobjc numpy scipy pillow python-dotenv requests
```

> `dashscope`（阿里云百炼 SDK）和 `beautifulsoup4`/`lxml`（browse_url 解析）按需安装。

### 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 DASHSCOPE_API_KEY
```

```env
# 必填
DASHSCOPE_API_KEY=sk-your-key-here

# 可选：多模态 OCR 开关
USE_MULTIMODAL_OCR=true
ALWAYS_USE_API=false

# 可选：Hermes Agent 地址（用于复杂任务深度分析）
HERMES_BASE_URL=http://127.0.0.1:8642
```

### 启动机器人

```bash
python3 run_bot.py
```

Bot 启动后会：
1. 检测微信窗口并截图
2. 初始化 SmartPerceptionPipeline（本地预判 + qwen3.6-flash API 兜底）
3. 加载全局状态（历史消息、记忆 wiki）
4. 进入 tick 循环（默认 5 秒间隔）

### 运行测试

```bash
python3 -m pytest tests/ -q
```

---

## 五、项目结构

```
wechat-mac-rpa/
├── wechat_rpa/
│   ├── bot/
│   │   └── wechat_bot.py              # L5: 主循环编排
│   ├── perception/
│   │   ├── smart_pipeline.py          # L3.5: 智能感知（本地预判 + API 兜底）
│   │   └── vision_pipeline.py         # L3.5: 纯本地 OCR 备用管道
│   ├── layout/
│   │   ├── layout_parser.py           # L3: 布局解析（聊天列表、消息区、输入框分割）
│   │   └── profile.py                 # L2: 布局配置（针对不同微信版本/分辨率）
│   ├── message/
│   │   └── extractor.py               # L3: 消息提取（聚类、sender 判定、时间戳过滤）
│   ├── session/
│   │   └── global_store.py            # L4: 全局消息存储 + 三层去重
│   ├── reply/
│   │   ├── policy.py                  # L4: 回复决策（群聊 @ 检测、冷却期）
│   │   ├── generator.py               # L4: 回复生成（Tool Calling + Skill 路由 + 双模型分流）
│   │   └── session_memory.py          # L4: 跨 tick 工具缓存
│   ├── action/
│   │   ├── message_sender.py          # L4: 消息发送（pbcopy + Command+V）
│   │   ├── chat_list_clicker.py       # L4: 聊天列表切换
│   │   └── login_recovery.py          # L4: 登录恢复（自动点击登录按钮）
│   ├── memory/
│   │   └── engine.py                  # L4: 长期记忆引擎（LLM Wiki + Overrides）
│   ├── tools/
│   │   ├── builtin_tools.py           # web_search / browse_url / get_weather / stock_query
│   │   └── tool_registry.py           # 工具注册与 OpenAI schema 转换
│   ├── capture/
│   │   └── window_capture.py          # L2: Quartz 窗口枚举 + screencapture 截图
│   ├── ocr/
│   │   └── vision_ocr.py              # L2: macOS Vision 框架文字识别
│   ├── models/
│   │   └── base.py                    # L1: 领域模型
│   ├── llm/
│   │   └── openclaw_client.py         # OpenAI-compatible API 客户端
│   ├── storage/
│   │   └── message_store.py           # 聊天记录持久化
│   └── utils/
│       └── debug_logger.py            # tick 级 debug JSON 记录
├── tests/                             # 测试套件（单元测试 + 集成测试）
├── wechat_rpa/tests/                  # 模块内测试（与源码同目录）
├── data/
│   ├── debug/                         # tick 级 debug JSON（运行时可观测）
│   ├── memory/wiki/                   # 用户/群聊/话题 wiki
│   └── screenshots/                   # 截图存档
├── docs/                              # 架构文档、踩坑记录、排障指南
└── run_bot.py                         # 生产环境入口
```

---

## 六、更多文档

- [架构设计](docs/02-architecture/ARCHITECTURE.md) — 分层架构、模块边界、依赖规则
- [模块索引](docs/02-architecture/MODULE_INDEX.md) — 改代码前先看这个
- [踩坑记录](docs/04-troubleshooting/LESSONS_LEARNED.md) — 避免重复踩坑
- [Tick 排查指南](docs/04-troubleshooting/TICK_INVESTIGATION_GUIDE.md) — 消息未回复时如何定位
- [日志设计](docs/03-guides/LOGGING_DESIGN.md) — debug JSON 结构和可观测性

---

## 七、免责声明

本项目仅用于个人学习和技术研究。使用自动化工具操作微信可能违反微信用户协议，请自行评估风险。本项目不对任何账号封禁或数据损失负责。
