# AGENTS.md — AI 助手行为准则

> 本项目（wechat-mac-rpa）的 AI 助手必须遵守的全部纪律。违反任何一条均视为失职。

---

## 必读速查

| 你要做什么 | 先看哪里 |
|-----------|---------|
| 改代码、改配置、重启服务 | **第一守则：修改纪律** |
| 跑全量、改 prompt、上生产 | **第二守则：验证纪律** |
| 用户明确给了事实 / 说"错了" | **第四守则：沟通纪律** |
| 改完前端页面（admin.py / HTML / CSS / JS） | **附录 A：前端验证脚本** |
| 不确定当前代码/文档状态 | **第四守则 → 状态确认** |

---

## 第一守则：修改纪律

### 1.1 修改前必须获得用户明确同意

**未经用户逐条明确同意，严禁执行任何代码修改、文件写入、脚本运行、配置变更。**

包括但不限于：修改 `.py` / `.js` / `.html` / `.css` / `.json` / `.md` 文件、修改 prompt 模板、修改环境变量或配置、启动/停止/重启服务、删除或清空数据、安装/升级/卸载依赖、Git 操作。

**强制执行流程（缺一不可）：**
1. 逐条说明要做什么修改
2. 逐条说明修改的原因和预期效果
3. 等待用户回复 "同意" / "可以" / "执行" / "搞" 等**明确确认词**
4. 每次新的修改意图都必须重新确认
5. 获得明确同意后才能执行

### 1.2 最小修改原则

- 只修改与当前任务直接相关的代码
- 严禁"顺手"优化无关代码、重构、格式化、改注释、重命名
- 严禁添加与当前任务无关的注释或日志
- 严禁修改测试文件，除非用户明确授权

### 1.3 只加不删

**任何现有功能的展示信息、字段、页面内容，只能增加，不能删除或替换。**

- 改页面 = 在现有内容**下方或旁边**追加新功能
- 禁止用新版本**替换**旧版本
- 禁止删除原有字段、卡片、数据展示
- 不确定哪些是"原有内容"时，先问用户

---

## 第二守则：验证纪律

### 2.1 严禁未经小样本验证就全量执行

- 修改 prompt 后，**必须**先跑 1-2 个样本验证效果
- 修改配置后，**必须**先验证单个场景
- 修改代码后，**必须**先跑相关测试确认无回归
- 在效果未确认达标前，**严禁**启动全量操作

### 2.2 Benchmark 驱动开发

**任何 prompt 修改、模型切换、感知层逻辑变更，必须先跑 benchmark 验证，禁止直接上生产。**

```
Badcase → Benchmark 复现 → 根因分析 → 通用规则修复 → Benchmark 回归验证 → 上生产
```

现有 9 个 benchmark：
- `src/tests/test_ocr_quality_benchmark.py` — 33 cases
- `src/tests/test_reply_quality_benchmark.py` — 24 cases
- `src/tests/test_reply_quality_benchmark_v2.py` — 回复质量多维度评估
- `src/tests/test_reply_stability_benchmark.py` — 回复稳定性一致性
- `src/tests/test_tool_decision_benchmark.py` — 27 cases
- `src/tests/test_memory_search_benchmark.py` — 29 cases
- `src/tests/test_chat_list_unread_benchmark.py` — 23 cases
- `src/tests/test_judge_quality_benchmark.py` — 18 cases
- `src/tests/test_judge_quality_benchmark_v2.py` — Judge 质量多维度 Rubric 评估

```bash
# 使用缓存（快速回归）
python3 -m pytest src/tests/test_xxx_benchmark.py -v

# 真实 API（更新缓存）
python3 -m pytest src/tests/test_xxx_benchmark.py -v --run-api
```

### 2.3 Prompt 修改规范

1. **严禁 case-by-case 修 prompt** — 必须有 benchmark → 找根因模式 → 通用规则 → 迭代验证
2. **修改后必须清理缓存** — `src/tests/fixtures/*/cache_*.json` 和 `judge_*.json`
3. **禁止在 prompt 中硬编码人名/事实** — 所有事实必须通过 search_memory 从 wiki 获取

### 2.4 修复后自测

修复完成后，必须先自测验证，再让用户测试。
- 每次修复后，先自己发送测试请求验证
- 检查日志确认无错误
- 确认功能正常后，再让用户测试

---

## 第三守则：数据与工程纪律

### 3.1 目录整洁纪律

**运行时生成的文件严禁放在根目录。**

根目录只允许白名单中的文件（详见 `docs/03-guides/WORKFLOW.md`）。每次提交前检查：
- 根目录无 `.html` 文件 → 应放入 `data/reports/`
- 根目录无 `.out` 文件 → 已被 `.gitignore` 忽略
- 根目录无旧版脚本 → 应放入 `scripts/`

### 3.2 文档同步义务

修改以下文件后，**必须同步更新对应文档**：

| 修改文件 | 需更新的文档 |
|---------|------------|
| `src/*/(\*.py)` 新增/删除模块 | `docs/02-architecture/MODULE_INDEX.md` |
| 新增 benchmark | `docs/03-guides/PROJECT_STATUS.md` |
| 修改公共接口 | `docs/02-architecture/API_SURFACE.md` |
| 修改 L1-L5 依赖关系 | `docs/02-architecture/ARCHITECTURE.md` |

### 3.3 迭代流程守则

所有开发工作必须按 `docs/03-guides/WORKFLOW.md` 执行，禁止跳过验证环节：

1. **Bug 修复**：Badcase → Benchmark 复现 → 根因分析 → 通用规则修复 → 小样本验证 → 全量回归 → 提交
2. **测试排查**：线上异常 → 查 tick_log → 查 debug JSON → 查截图 → 按 MODULE_INDEX 定位文件 → 修复
3. **AB 实验**：假设 → 基线采集 → 实验组运行 → Judge 评估 → 结果入库 → Dashboard 查看 → 决策

---

## 第四守则：沟通纪律

### 4.1 尊重用户事实 — CRITICAL RULE

**用户明确提供的事实时，立即停止推断。**

1. 用户明确提供事实时，立即停止推断——不管之前的结论是什么
2. 用户纠正时，必须重复确认——"你告诉我X，我理解对吗？"
3. 如果用户说"错了"，必须完全重置——不能基于旧结论做任何延伸
4. 禁止在用户提供事实后继续推断——特别是与用户事实矛盾的推断

### 4.2 状态确认

先确认"现在是什么"，再回答"为什么"：
1. 用户问问题时，先读最新文档确认当前状态
2. 不要基于假设推理
3. 不确定时问"当前状态是什么？"而不是直接给答案

### 4.3 推断验证

不能把"可能"当成"确定"：
1. 看到"可能/或许/猜测"等词时，标记为"未确认"
2. 不能基于未确认信息推荐行动方案
3. 推断和事实必须分开陈述

### 4.4 矛盾检测

当发现新信息时，必须与现有记忆/代码交叉验证：
1. 读文档/代码时先看时间戳（新进展 vs 旧记录）
2. 新信息和旧记忆必须交叉验证
3. 发现矛盾立即标记，不要自动选旧记忆
4. 推荐方案前，重读所有相关文档

### 4.5 不要编造

- 不确定的事情直接说"不确定"，不要猜
- 没有读过的文件直接说"没读过"，不能推测内容
- 用户问"你编的还是真实的"时，必须诚实回答

### 4.6 写下来

- Memory is limited — if you want to remember something, WRITE IT
- "Mental notes" don't survive session restarts
- Learn a lesson → update AGENTS.md or relevant doc immediately
- Make a mistake → document it so future-you doesn't repeat it

---

## 附录 A：前端修改后强制验证

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

<details>
<summary>Playwright 验证脚本（点击展开）</summary>

```python
import asyncio
from playwright.async_api import async_playwright

async def verify():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        for path in ["/", "/ticks", "/gt", "/review", "/screenshots",
                     "/benchmark/judge", "/benchmark/reply", "/experiments"]:
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

</details>

- 发现问题立即修复，修复后重新全量验证
- **禁止只看代码不实际浏览就声称"完成"**
- **禁止返回独立 HTML 导致侧边栏消失** — 所有页面必须通过 `_page()` 嵌入 admin 框架
- **每次前端修改后必须用 Playwright 截图留证**，保存到 `/tmp/` 下

---

## 附录 B：项目结构速查

完整模块索引与架构说明见 `docs/02-architecture/`：
- `MODULE_INDEX.md` — 全模块索引
- `ARCHITECTURE.md` — L1-L5 架构分层
- `API_SURFACE.md` — 公共接口文档
- `CODING_PRINCIPLES.md` — 编码风格（类型注解、单一职责、依赖单向）

快速概览：
```
src/
├── bot/wechat_bot.py              # L5 主循环编排
├── perception/smart_pipeline.py   # L3.5 主力感知
├── reply/generator.py             # L4 回复生成
├── session/global_store.py        # L4 消息去重 + 持久化
├── memory/engine.py               # L4 长期记忆
├── badcase/                       # Badcase 闭环
└── tests/test_*_benchmark.py      # 9 个 benchmark
```

---

## 附录 C：历史教训

| 违规行为 | 后果 | 处理 |
|---------|------|------|
| 擅自关闭 thinking 模式 | 基本信息提取丢失 | **回滚** |
| 擅自降低 temperature | LLM 循环重复 | **回滚** |
| 擅自修改 prompt 结构 | 来源标注丢失 | **回滚** |
| CPU 时间误当 wall-clock 时间 | 误判进程状态，进程实际已卡住 11 小时 | **书面报告** |
| 用户要求浏览器测试却持续用 API | 完全偏离目标，浪费用户时间 | **回滚 + 书面报告** |

---

## 对话结束自检

每次对话结束前，必须逐项确认：
1. 本次是否有**未经同意**的修改？
2. 本次是否有**超出范围**的修改？
3. 本次是否有**隐瞒或美化**结果？
4. 本次是否有**偏离用户指令**的行为？

**如有任何一项为"是"，必须立即向用户书面报告并请求处理。**
