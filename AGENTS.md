# AGENTS.md

本项目（wechat-mac-rpa）的 AI 助手行为准则。

## 核心原则

### 1. 修改前必须获得用户同意

**任何代码修改、配置变更、脚本执行，在执行前必须获得用户明确同意。**

包括但不限于：
- 修改 `.py` 文件
- 修改 prompt 模板
- 修改环境变量或配置
- 启动/停止/重启服务
- 删除或清空数据
- 安装/升级依赖

**执行流程：**
1. 说明要做什么修改
2. 说明修改的原因和预期效果
3. 等待用户回复 "同意"/"可以"/"执行" 等明确确认
4. 获得同意后才能执行

### 2. 最小修改原则

- 只修改与当前任务直接相关的代码
- 不要"顺手"优化无关代码
- 不要擅自重构、格式化、改注释

### 3. 执行后报告结果

- 执行完成后立即报告结果
- 如果有异常或错误，如实汇报
- 不要隐瞒问题或自行猜测原因

### 4. 验证优先

- 全量操作前必须先小样本验证
- 修改 prompt 后必须先跑 1-2 个样本验证效果
- 确认效果达标后才能启动全量

## 工程铁律（不可违反）

### Benchmark 驱动开发

**任何 prompt 修改、模型切换、感知层逻辑变更，必须先跑 benchmark 验证，禁止直接上生产。**

```
Badcase → Benchmark 复现 → 根因分析 → 通用规则修复 → Benchmark 回归验证 → 上生产
```

现有 5 个 benchmark：
- `src/tests/test_ocr_quality_benchmark.py` — 33 cases
- `src/tests/test_reply_quality_benchmark.py` — 24 cases
- `src/tests/test_tool_decision_benchmark.py` — 27 cases
- `src/tests/test_memory_search_benchmark.py` — 29 cases
- `src/tests/test_chat_list_unread_benchmark.py` — 23 cases

**运行方式：**
```bash
# 使用缓存（快速回归）
python3 -m pytest src/tests/test_xxx_benchmark.py -v

# 真实 API（更新缓存）
python3 -m pytest src/tests/test_xxx_benchmark.py -v --run-api
```

### Prompt 修改规范

1. **严禁 case-by-case 修 prompt** — 必须有 benchmark → 找根因模式 → 通用规则 → 迭代验证
2. **修改后必须清理缓存** — `src/tests/fixtures/*/cache_*.json` 和 `judge_*.json`
3. **禁止在 prompt 中硬编码人名/事实** — 所有事实必须通过 search_memory 从 wiki 获取

### 文档同步义务

修改以下文件后，**必须同步更新对应文档**：

| 修改文件 | 需更新的文档 |
|---------|------------|
| `src/*/(*.py)` 新增/删除模块 | `docs/02-architecture/MODULE_INDEX.md` |
| 新增 benchmark | `docs/03-guides/PROJECT_STATUS.md` |
| 修改公共接口 | `docs/02-architecture/API_SURFACE.md` |
| 修改 L1-L5 依赖关系 | `docs/02-architecture/ARCHITECTURE.md` |

## 项目结构速查

```
src/
├── bot/wechat_bot.py              # L5 主循环编排
├── perception/smart_pipeline.py   # L3.5 主力感知（本地预判 + API 兜底）
├── perception/weflow_pipeline.py  # L3.5 实验性：数据库驱动感知
├── reply/generator.py             # L4 回复生成（Agent 运行时 + 双模型路由）
├── reply/policy.py                # L4 回复决策
├── reply/session_memory.py        # L4 跨 tick 工具缓存
├── session/global_store.py        # L4 消息去重 + 持久化
├── memory/engine.py               # L4 长期记忆（LLM Wiki + Overrides）
├── tools/tool_registry.py         # L4 工具注册
├── action/message_sender.py       # L4 消息发送
├── layout/layout_parser.py        # L3 布局解析
├── message/extractor.py           # L3 消息提取
├── capture/window_capture.py      # L2 截图
├── ocr/vision_ocr.py              # L2 OCR
├── models/base.py                 # L1 领域模型
├── llm/openclaw_client.py         # LLM 客户端（Kimi 本地代理）
├── llm/qwen_client.py             # LLM 客户端（DashScope API）
├── badcase/                       # Badcase 闭环（生成器 / Judge Worker / 审核服务）
├── utils/                         # 共享工具（chat_utils / text_utils / xml_utils / debug_logger / llm_client / qwen_client）
└── tests/test_*_benchmark.py      # 5 个 benchmark
```

完整模块索引见 `docs/02-architecture/MODULE_INDEX.md`。

## 编码风格

见 `docs/02-architecture/CODING_PRINCIPLES.md`。

核心要求：
- 类型注解（`def func(x: int) -> str`）
- 单一职责（每个文件只做一件事）
- 依赖单向（上层调用下层，禁止反向依赖）

## 历史教训

- **擅自关闭 thinking 模式** → 导致基本信息提取丢失，必须回滚
- **擅自降低 temperature** → 导致 LLM 循环重复，必须回滚
- **擅自修改 prompt 结构** → 导致来源标注丢失，必须回滚
- **CPU 时间误当 wall-clock 时间** → 误判进程状态，进程实际已卡住 11 小时
