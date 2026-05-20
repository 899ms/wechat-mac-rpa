# WeChat Mac RPA

基于多模态视觉感知与 LLM Agent 的 macOS 微信自动化框架。

**不是协议逆向，不是 Hook，不碰微信数据库。** 我们把微信当作黑盒 GUI 应用，用计算机视觉读取界面，用大语言模型理解对话，用系统级自动化操作界面。微信更新 UI 只是换了一套视觉输入，不需要追着协议跑。

---

## 核心设计

### 分层架构（L1-L5）

```
L5  Bot Orchestrator        ← 主循环编排：感知 → 会话 → 决策 → 生成 → 行动
L4  Session / Reply / Action ← 去重、决策、生成、发送
L3.5 SmartPerceptionPipeline ← 像素差异预判 + qwen3.6-flash API 兜底
L3  Layout / Message         ← 布局解析、消息提取
L2  OCR / Capture / Profile  ← Vision 文字识别、窗口截图、布局配置
L1  Domain Models            ← Point, Rect, ChatMessage, PerceptionResult
```

每层只向下依赖。Bot 层只消费 `PerceptionResult` 和 `ChatMessage`，不直接接触 OCR、截图或布局解析。

### 双模型路由

单一模型无法同时满足"秒回闲聊"和"深度推理"。

- **日常对话** → `deepseek-v4-flash`（低延迟、Tool Calling）
- **Skill 匹配** → Hermes Agent（长上下文、深度推理）

两者拥有独立的 system prompt 和工具体系。ReplyGenerator 是一个完整的 Agent 运行时：多轮工具调用、超时保护、空回复自动重试。

### 记忆系统（LLM Wiki）

Bot 不是无状态聊天机器人。每个联系人、群聊、话题都有独立的 **Wiki**（Markdown 格式），由 LLM 自动维护、人工可覆写。

- **自动构建**：从聊天历史提取实体、关系、偏好，生成结构化 Wiki
- **Overrides**：人工可覆写任意字段，LLM 更新时自动保护（`# OVERRIDE` 标记）
- **实时检索**：`search_memory` 工具在回复前自动查询相关上下文，召回率 96.6%
- **隐私优先**：所有数据本地存储（`data/memory/wiki/`），不上传云端

### 轻量化日常对话 Agent

我们做了一个刻意的设计：**日常闲聊不需要重型 Agent**。

- **日常对话** → `deepseek-v4-flash`（低延迟、Tool Calling、成本可控）
- **深度 Skill** → Hermes Agent（长上下文、复杂推理、多轮规划）

ReplyGenerator 本身就是一个完整的 Agent 运行时：多轮工具调用、超时保护、空回复自动重试。但**默认路径是轻量的**——不需要时绝不加载重型上下文。

### 智能感知管道

传统方案要么全走本地 OCR（准确率有限），要么全走云端 API（成本高、延迟大）。我们设计了两级管道：

1. **像素差异预判**：基于 ROI 哈希判断截图是否有实质变化，无变化时直接复用上轮结果，**零 API 调用**
2. **多模态 API 兜底**：消息内容交给 qwen3.6-flash 识别，群聊昵称、emoji、换行格式全部保留

实测 **92.6% 的 tick 无需调用 API**。

---

## 工程体系

> 这不是一个玩具项目。我们建立了完整的工程闭环：Badcase 发现 → Benchmark 量化 → 根因分析 → 通用规则修复 → 回归验证。

### Benchmark 驱动开发

**5 个独立 benchmark，136 个 case，覆盖核心链路：**

| Benchmark | Cases | 评估方式 | 当前状态 |
|-----------|-------|---------|---------|
| **Reply Quality** | 24 | LLM-as-a-Judge + 18 个自定义 Rubric | ✅ 100% |
| **Tool Decision** | 27 | Binary + Judge Rubric（对抗性 case） | 🟡 81.5% |
| **Memory Search** | 29 | Precision/Recall/F1 | 🟡 96.6% |
| **Chat List Unread** | 23 | Precision/Recall | ✅ 100% |
| **OCR Quality** | 33 | Sender/Text/ChatName/Count | 🔴 24.2% |

**评估基础设施：**
- **LLM-as-a-Judge**：Reply Quality 和 Tool Decision 对抗性 case 使用 `deepseek-v4-pro` 做结构化 Rubric 评估（非关键词匹配）
- **缓存机制**：Judge 结果按内容哈希缓存（`judge_{hash}.json`），支持快速回归
- **pytest 集成**：所有 benchmark 可直接用 `pytest -v` 运行，CI 友好

**开发铁律：** 任何 prompt 修改、模型切换、感知层逻辑变更，必须先跑 benchmark 验证，禁止直接上生产。

### Badcase 闭环

```
生产 tick → case_generator.py 提取异常 → judge_worker.py 自动评估
                                               ↓
                                    review_server.py 人工审核
                                               ↓
                                    加入 benchmark → 根因分析
                                               ↓
                                    通用规则修复 → benchmark 回归验证
                                               ↓
                                    通过 → 上生产
```

生产环境中的每一条异常 tick 都被自动捕获、评估、归档。不是"修完就忘"，而是形成可追溯、可回归的 case 资产。

### 全链路 Profile 监控

**不是"感觉慢"，而是数据驱动。**

整个链路已植入统一的 `[Perf]` 打点：

```
[Perf][Capture] total=650ms find_window=120ms screenshot=380ms validate=150ms
[Perf][OCR] recognize: 1200ms, elements=47
[Perf][Layout] parse: 580ms bubbles=420ms chat_list=160ms
[Perf][Generate] total=7200ms sp=80ms tc=120ms up=1800ms route=2200ms llm=2800ms parse=200ms
[Perf][Memory] self=45ms other=380ms group=120ms mentions=850ms
[Perf][Sender] total=3200ms read_clipboard=15ms activate=200ms pbcopy=80ms ...
```

基于日志数据驱动，我们编写了 `PERFORMANCE_SPEC.md`（`docs/02-architecture/specs/PERFORMANCE_SPEC.md`），包含：
- 各阶段耗时基线（无消息 tick ~3s，完整链路 ~18s）
- 瓶颈分解与优先级排序
- 优化方案设计（hash 缓存、skill 缓存、memory 读缓存等）
- A/B 测试指标定义

---

## 快速开始

### 环境

- macOS 12+
- Python 3.10+
- 微信 Mac 版（推荐 4.1.8）

### 安装

```bash
git clone <repo>
cd wechat-mac-rpa
pip install -r requirements.txt
```

### 配置

```bash
# API Key（感知层 + LLM 调用）
export DASHSCOPE_API_KEY=your_key

# 可选：Kimi 本地代理（回复生成）
export OPENCLAW_API_KEY=your_key

# 可选：启用 WeFlow 数据库驱动感知（实验性）
export WEFLOW_MODE=weflow
```

### 启动

```bash
# 生产环境
python3 run_bot.py

# 指定配置
USE_MULTIMODAL_OCR=false python3 run_bot.py   # 纯本地 OCR 模式
```

### 测试

```bash
# 全量 benchmark 回归（使用缓存）
python3 -m pytest src/tests/test_ocr_quality_benchmark.py -v
python3 -m pytest src/tests/test_reply_quality_benchmark.py -v
python3 -m pytest src/tests/test_tool_decision_benchmark.py -v
python3 -m pytest src/tests/test_memory_search_benchmark.py -v
python3 -m pytest src/tests/test_chat_list_unread_benchmark.py -v

# 真实 API（更新缓存）
python3 -m pytest src/tests/test_reply_quality_benchmark.py -v --run-api
```

---

## 项目结构

```
wechat-mac-rpa/
├── src/
│   ├── bot/wechat_bot.py              # L5: 主循环编排
│   ├── perception/
│   │   ├── smart_pipeline.py          # L3.5: 智能感知（本地预判 + API 兜底）
│   │   ├── vision_pipeline.py         # L3.5: 纯本地 OCR 备用管道
│   │   ├── weflow_pipeline.py         # L3.5: 数据库驱动感知（实验性）
│   │   └── weflow_client.py           # L3.5: WeFlow 客户端
│   ├── layout/
│   │   ├── layout_parser.py           # L3: 布局解析
│   │   └── profile.py                 # L2: 布局配置
│   ├── message/extractor.py           # L3: 消息提取
│   ├── session/global_store.py        # L4: 全局消息存储（LCS 去重 + 持久化）
│   ├── reply/
│   │   ├── generator.py               # L4: 回复生成（Agent 运行时 + 双模型路由）
│   │   ├── policy.py                  # L4: 回复决策
│   │   └── session_memory.py          # L4: 跨 tick 工具缓存
│   ├── memory/engine.py               # L4: 长期记忆（LLM Wiki + Overrides）
│   ├── tools/                         # L4: 工具注册 + 内置工具
│   ├── action/
│   │   ├── message_sender.py          # L4: 消息发送
│   │   ├── chat_list_clicker.py       # L4: 聊天列表切换
│   │   └── login_recovery.py          # L4: 登录恢复
│   ├── capture/window_capture.py      # L2: 窗口截图
│   ├── ocr/vision_ocr.py              # L2: macOS Vision 文字识别
│   ├── models/base.py                 # L1: 领域模型
│   ├── llm/
│   │   ├── openclaw_client.py         # LLM 客户端（Kimi 本地代理）
│   │   └── qwen_client.py             # LLM 客户端（DashScope API）
│   ├── utils/                         # L1-L5 共享工具
│   ├── badcase/                       # Badcase 闭环体系
│   │   ├── case_generator.py          # 从 tick 数据生成 benchmark case
│   │   ├── judge_worker.py            # 异步 Judge LLM 评估
│   │   └── review_server.py           # 人工审核 Web 服务
│   └── tests/
│       ├── test_ocr_quality_benchmark.py        # 33 cases
│       ├── test_reply_quality_benchmark.py      # 24 cases
│       ├── test_tool_decision_benchmark.py      # 27 cases
│       ├── test_memory_search_benchmark.py      # 29 cases
│       ├── test_chat_list_unread_benchmark.py   # 23 cases
│       └── ...                          # 单元测试
├── docs/
│   ├── 01-quickstart/                   # 快速开始
│   ├── 02-architecture/                 # 架构设计 + API 接口 + 模块索引
│   │   ├── ARCHITECTURE.md
│   │   ├── API_SURFACE.md              # 公共接口速查表
│   │   ├── MODULE_INDEX.md             # 按问题/文件索引
│   │   ├── CODING_PRINCIPLES.md
│   │   └── specs/                      # 各模块 SPEC
│   ├── 03-guides/                       # 使用指南 + 项目状态
│   ├── 04-troubleshooting/              # 问题排查 + 经验教训
│   └── 05-meta/                         # 实验记录 + 审计
├── data/
│   ├── debug/                           # tick 级 debug JSON
│   ├── memory/wiki/                     # 用户/群聊/话题 wiki
│   └── screenshots/                     # 截图存档
└── run_bot.py                           # 生产环境入口
```

---

## 更多文档

| 文档 | 说明 |
|------|------|
| [架构设计](docs/02-architecture/ARCHITECTURE.md) | L1-L5 分层架构、依赖规则、边界约束 |
| [API 接口速查](docs/02-architecture/API_SURFACE.md) | 当前生产代码的公共接口，可直接复制粘贴 |
| [模块索引](docs/02-architecture/MODULE_INDEX.md) | "消息识别错了"→改哪个文件 |
| [编码原则](docs/02-architecture/CODING_PRINCIPLES.md) | 类型注解、单一职责、单向依赖 |
| [项目进度](docs/03-guides/PROJECT_STATUS.md) | 当前状态、活跃问题、benchmark 结果 |
| [性能优化 Spec](docs/02-architecture/specs/PERFORMANCE_SPEC.md) | 全链路 profiling 点、瓶颈分析、优化方案 |
| [踩坑记录](docs/04-troubleshooting/LESSONS_LEARNED.md) | 历史教训、常见错误模式 |

---

## 免责声明

本项目仅用于个人学习和研究目的。使用自动化工具操作微信可能违反微信用户协议，请自行评估风险。本项目作者不对任何使用后果负责。
