# AGENTS.md

本项目（wechat-mac-rpa）的 AI 助手行为准则。

## 核心原则

### 0. 改动原则：只加不删

**任何现有功能的展示信息、字段、页面内容，只能增加，不能删除或替换。**

- 改页面 = 在现有内容**下方或旁边**追加新功能
- 禁止用新版本**替换**旧版本
- 禁止删除原有字段、卡片、数据展示
- 不确定哪些是"原有内容"时，先问用户

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

现有 8 个 benchmark：
- `src/tests/test_ocr_quality_benchmark.py` — 33 cases
- `src/tests/test_reply_quality_benchmark.py` — 24 cases
- `src/tests/test_reply_quality_benchmark_v2.py` — 回复质量多维度评估
- `src/tests/test_reply_stability_benchmark.py` — 回复稳定性一致性
- `src/tests/test_tool_decision_benchmark.py` — 27 cases
- `src/tests/test_memory_search_benchmark.py` — 29 cases
- `src/tests/test_chat_list_unread_benchmark.py` — 23 cases
- `src/tests/test_judge_quality_benchmark.py` — 18 cases（meta-benchmark：评估 Judge LLM 自身准确率）
- `src/tests/test_judge_quality_benchmark_v2.py` — Judge 质量多维度 Rubric 评估

**运行方式：**
```bash
# 使用缓存（快速回归）
python3 -m pytest src/tests/test_xxx_benchmark.py -v

# 真实 API（更新缓存）
python3 -m pytest src/tests/test_xxx_benchmark.py -v --run-api
```

### 迭代流程守则

所有开发工作必须按 `docs/03-guides/WORKFLOW.md` 执行，禁止跳过验证环节：

1. **Bug 修复**：Badcase → Benchmark 复现 → 根因分析 → 通用规则修复 → 小样本验证 → 全量回归 → 提交
2. **测试排查**：线上异常 → 查 tick_log → 查 debug JSON → 查截图 → 按 MODULE_INDEX 定位文件 → 修复
3. **AB 实验**：假设 → 基线采集 → 实验组运行 → Judge 评估 → 结果入库 → Dashboard 查看 → 决策
4. **文档同步**：修改代码后必须在同一 commit 中更新对应文档

### 目录整洁纪律

**运行时生成的文件严禁放在根目录。**

根目录只允许白名单中的文件（详见 WORKFLOW.md）。
每次提交前检查：
- 根目录无 `.html` 文件 → 应放入 `data/reports/`
- 根目录无 `.out` 文件 → 已被 `.gitignore` 忽略
- 根目录无旧版脚本 → 应放入 `scripts/`

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
├── action/ui_interactor.py        # L4 UI 交互抽象
├── action/message_sender.py       # L4 消息发送
├── action/chat_list_clicker.py    # L4 聊天列表切换
├── layout/layout_parser.py        # L3 布局解析
├── message/extractor.py           # L3 消息提取
├── capture/window_capture.py      # L2 截图
├── ocr/vision_ocr.py              # L2 OCR
├── models/base.py                 # L1 领域模型
├── llm/openclaw_client.py         # LLM 客户端（Kimi 本地代理）
├── llm/qwen_client.py             # LLM 客户端（DashScope API）
├── logging/bot_logger.py          # 结构化日志与全链路追踪
├── badcase/                       # Badcase 闭环（数据库 / 生成器 / Judge Worker / 审核服务）
├── utils/                         # 共享工具
└── tests/test_*_benchmark.py      # 8 个 benchmark
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

## 全局纪律（from 根目录 AGENTS.md — 强制约束）

### 纪律 1：严禁擅自执行任何操作
未经用户逐条明确同意，严禁执行任何代码修改、文件写入、脚本运行、配置变更。
每次新的修改意图都必须重新确认。

### 纪律 2：严禁超出范围的修改
严禁"顺手"修改与当前任务无关的代码、重构、格式化、重命名无关代码。

### 纪律 3：严禁隐瞒或美化结果
执行完成后必须如实报告结果。严禁在报告中说"测试通过"如果实际有失败。

### 纪律 4：严禁未经小样本验证就全量执行
全量操作前必须先小样本验证。修改 prompt 后必须先跑 1-2 个样本验证效果。

### 纪律 5：严禁偏离用户指令
用户纠正方向后，必须立即停止当前错误方向。严禁以"环境限制"为由擅自用替代方案而不告知。

### 对话结束自检
1. 本次是否有未经同意的修改？
2. 本次是否有超出范围的修改？
3. 本次是否有隐瞒或美化结果？
4. 本次是否有偏离用户指令的行为？

## 操作纪律（from kimi/OpenClaw AGENTS.md）

### 尊重用户事实 — CRITICAL RULE

**用户明确提供的事实时，立即停止推断。**
1. 用户明确提供事实时，立即停止推断——不管之前的结论是什么
2. 用户纠正时，必须重复确认——"你告诉我X，我理解对吗？"
3. 如果用户说"错了"，必须完全重置——不能基于旧结论做任何延伸
4. 禁止在用户提供事实后继续推断——特别是与用户事实矛盾的推断

### 前端修改后强制验证

**任何修改前端页面相关代码（admin.py、HTML 模板、CSS、JS）后，必须用 Playwright 验证所有页面正常，禁止只看代码就声称完成。**

验证清单（必须逐项确认）：
1. **所有页面 HTTP 200**，不是空白页/500 错误
2. **Admin 侧边栏是否保留**（不能把独立 HTML 直接返回，必须嵌入 `_page()` 框架）
3. **页面不出现原始 JSON/代码**（检查 `.inner_text()` 不包含 `[{`、`is_badcase` 等字段名）
4. 所有链接、按钮是否可点击且有响应
5. 数据是否正确展示（不是空白/报错），关键指标数字 > 0
6. 分页、筛选、跳转等交互是否生效
7. 图片/截图是否能正常加载
8. **表格、卡片、指标区布局是否整齐**（`page.locator('.card').count()` > 0）

**必须检查的页面**（admin.py 全量）：
- `/` Dashboard
- `/ticks` Tick 查看
- `/gt` GT 标注
- `/review` 人工审核
- `/screenshots` 截图 OCR
- `/benchmark/judge` Judge 质量
- `/benchmark/reply` 回复质量
- `/experiments` 实验管理

验证脚本：
```python
import asyncio
from playwright.async_api import async_playwright

async def verify():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        for path in ["/", "/ticks", "/gt", "/review", "/screenshots", "/benchmark/judge", "/benchmark/reply", "/experiments"]:
            await page.goto(f"http://localhost:8766{path}")
            assert page.url.endswith(path), f"跳转失败: {path}"
            text = await page.inner_text("body")
            assert "[{" not in text and "is_badcase" not in text, f"暴露原始数据: {path}"
            count = await page.locator(".card").count()
            assert count > 0 or path in ["/gt", "/review"], f"布局异常: {path}"
            await page.screenshot(path=f"/tmp/admin_{path.replace('/', '_')}_{int(time.time())}.png", full_page=True)
        await browser.close()

asyncio.run(verify())
```

- 发现问题立即修复，修复后重新全量验证
- **禁止只看代码不实际浏览就声称"完成"**
- **禁止返回独立 HTML 导致侧边栏消失** — 所有页面必须通过 `_page()` 嵌入 admin 框架
- **每次前端修改后必须用 Playwright 截图留证**，保存到 `/tmp/` 下

### 修复后自测

修复完成后，必须先自测验证，再让用户测试。
- 每次修复后，先自己发送测试请求验证
- 检查日志确认无错误
- 确认功能正常后，再让用户测试

### 矛盾检测

当发现新信息时，必须与现有记忆/代码交叉验证：
1. 读文档/代码时先看时间戳（新进展 vs 旧记录）
2. 新信息和旧记忆必须交叉验证
3. 发现矛盾立即标记，不要自动选旧记忆
4. 推荐方案前，重读所有相关文档

### 推断验证

不能把"可能"当成"确定"：
1. 看到"可能/或许/猜测"等词时，标记为"未确认"
2. 不能基于未确认信息推荐行动方案
3. 推断和事实必须分开陈述

### 状态确认

先确认"现在是什么"，再回答"为什么"：
1. 用户问问题时，先读最新文档确认当前状态
2. 不要基于假设推理
3. 不确定时问"当前状态是什么？"而不是直接给答案

### 写下来

- Memory is limited — if you want to remember something, WRITE IT
- "Mental notes" don't survive session restarts
- Learn a lesson → update AGENTS.md or relevant doc immediately
- Make a mistake → document it so future-you doesn't repeat it

### 不要编造

- 不确定的事情直接说"不确定"，不要猜
- 没有读过的文件直接说"没读过"，不能推测内容
- 用户问"你编的还是真实的"时，必须诚实回答
