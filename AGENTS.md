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

### 1.3 性能/超时参数修改纪律（新增）

**修改任何 timeout、sleep、轮询间隔、缓存策略等性能参数前，必须先测量实际值。**

严禁事项：
- **严禁**未测量实际耗时就更改 API timeout（如从 60s 降到 15s）
- **严禁**未测量实际负载就更改轮询间隔
- **严禁**未验证就调整阈值（如像素 diff 阈值、防抖时间）

强制执行流程：
1. **必须**先测量当前实际值（如 `time python3 -c "..."`）
2. **必须**说明当前值、目标值、修改理由
3. **必须**等用户确认后再改
4. 修改后**必须**验证是否达到预期（如 timeout 是否足够、是否还有超时）

**违反后果：** 立即回滚，书面报告违规详情。

### 1.4 只加不删

**任何现有功能的展示信息、字段、页面内容，只能增加，不能删除或替换。**

- 改页面 = 在现有内容**下方或旁边**追加新功能
- 禁止用新版本**替换**旧版本
- 禁止删除原有字段、卡片、数据展示
- 不确定哪些是"原有内容"时，先问用户

### 1.5 Python 长进程重启纪律

**任何修改 `scripts/admin.py`（或任何其他长运行 Python 进程）的代码后，必须重启进程才能生效。**

- `admin.py` 是 uvicorn 长运行进程，**不会自动热重载**
- 修改后必须：`kill <pid>` 然后 `python scripts/admin.py`
- 严禁在未重启的情况下宣称"改好了"或让用户去刷新页面验证
- **同理**：修改 `src/` 下的任何模块后，如果 `run_bot.py` 或 `admin.py` 已经运行，必须重启才能加载新代码

**违反后果：** 立即书面报告违规详情，重新执行正确验证流程。

### 1.6 正向实现与根因追溯纪律（严禁事后打补丁）

**所有功能开关必须在生成阶段正向实现，严禁在输出完成后用任何手段事后打补丁。遇到异常现象必须先追溯根因，禁止在症状层面修 bug。干不了就直接汇报，绝不事后打补丁。**

#### 什么是"事后打补丁"

在输出/数据已经生成后，用正则、字符串替换、条件过滤等手段"删掉"或"修改"已生成的内容，来模拟"这个功能没开启"。

典型案例：
- ❌ `no_time` 实验：prompt 生成后，用 `re.sub` 把"当前时间"行删掉 → 事后打补丁
- ❌ 看到 wiki 里时间戳太多，用正则过滤掉 → 不问"这些时间戳从哪来" → 症状修 bug
- ❌ 用 `str.replace` 把 system prompt 里的"不回复"改成"可以回复" → 事后改文本

正确做法：
- ✅ `_build_user_prompt` 里根据开关决定是否拼接"当前时间"行
- ✅ `_system_prompt` 里根据开关决定是否包含"回复克制原则"section
- ✅ `_format_message_line` 里根据开关决定是否加时间标签

#### 三个严禁

1. **严禁事后模拟开关** — 需要开关控制的功能，必须从源头生成阶段根据开关决定是否输出。禁止在生成后用任何手段（正则、字符串替换、条件过滤）删掉或修改来模拟关闭。**干不了就直接汇报，绝不事后打补丁。**
2. **严禁症状修 bug** — 看到异常时必须先追问"为什么会有这个问题"，追溯数据源头或生成逻辑。禁止看到什么异常就改什么，而不问根因。
3. **严禁用脏数据跑实验** — 实验前必须抽样检查输入数据质量。数据有污染时，实验结果不可信，必须先清数据再跑实验。

今天教训：
- `no_time` 实验用正则从已有 prompt 中删时间戳 → 误伤记忆来源、删不净、生产无法复现 → 违反纪律 1
- 看到 diff 时间戳多就改进正则 → 没追问"为什么 wiki 里会有一大串时间戳" → 违反纪律 2
- 用包含异常时间戳列表的 wiki 数据跑实验 → 实验基线被污染 → 违反纪律 3
- 用 `_apply_experiment_modifications` 方法"结构化地"事后修改 prompt → 换了个姿势的事后打补丁 → 违反纪律 1

### 1.7 调研优先纪律

**用户给了明确参考（网站、截图、竞品）时，必须先调研参考，严禁凭经验盲写。**

今天教训：用户说"去 diffguru.com 看了"→我没有先调研参考，凭经验写了 table-based diff→用户说"完全不对"

### 1.8 不替用户决定隐藏纪律

**严禁替用户决定什么内容应该折叠、截断或隐藏。**

今天教训：把 diff 包在 `<details>` 里折叠、截断 150 字符→用户说"不能上下拉查看""提示词没显示全"

### 1.9 给 LLM 原始事实，不给二手加工信息

**给 LLM 的输入必须是原始事实（恒定、不可推导），严禁给易腐的二手加工信息。**

- 相对时间（"3分钟前""昨晚"）是快照，生成后就开始过期，Bot 推理时已经不准
- 绝对时间（"2026-05-28 08:46"）是恒定事实，LLM 自己可以根据当前时间推导相对关系
- 同样的原则适用于任何可计算信息：给原始数据，不给预计算结论

今天教训：给消息加"刚刚""3分钟前"等相对标签 → 随着时间推移信息失真 → 改为绝对时间戳

### 1.10 消费端同步纪律（新增）

**修改数据 schema、评分体系、分数范围、输出格式时，必须同步检查所有消费端，严禁只改生成端不改展示端。**

消费端包括但不限于：
- Admin 页面（admin.py）的 HTML 渲染逻辑
- 实验系统（run_experiment.py）的结果解析
- 数据库查询和报表逻辑
- 任何硬编码的分母、阈值、进度条计算

今天教训：
- judge 评分从 0-50 改为 0-100，但 admin.py 硬编码了 `/50` 和 `/5` → 展示溢出
- 维度进度条按 5 分制计算，`100/5=20` 倍 → 进度条 `█` 满屏溢出
- is_badcase 显示 `0/1` → 用户看不懂

强制执行：
1. 改分制/score 范围前，grep 所有消费端的硬编码数字
2. 改输出格式前，检查所有解析该格式的代码
3. 前端修改后必须用 Playwright 截图验证（见附录 A）

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

**严禁说"等下一个 tick 来验证"或"让用户先试试看"。** 能本地测的必须本地测完再汇报。

今天教训：
- 改完 judge prompt 后说"等下一个 tick 触发 judge 后再看效果" → 用户批评"能自己测的自己先测完"
- 正确做法：用之前失败的 tick 数据直接调用 `_judge()` 验证，不用等生产环境

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

### 3.4 正则使用纪律

**项目中真正需要正则的场景极少。能用字符串操作（`str.find`、`split`、`replace`、`in` 运算符）解决的，严禁用正则。**

正则的合法使用场景（白名单）：
- 时间戳格式匹配（`12:34`、`昨天 12:34`、`YYYY-MM-DD` 等固定模式）
- 从外部不可控输入中提取结构化数据（如 URL query string，但优先用 `urllib.parse`）

严禁使用正则的场景：
- **字符串清洗**：空白清理用 `' '.join(s.split())`，空行清理用 `splitlines` + `filter`，禁止 `re.sub(r'\s+', ' ', s)`
- **XML/HTML 解析**：必须用 `xml.etree.ElementTree` 或 `BeautifulSoup`，禁止正则提取标签
- **前缀/后缀处理**：用 `str.startswith`/`str.endswith`/`str.rfind`，禁止 `re.sub(r'...$', '', s)`
- **字符集合判断**：用 `any(c in text for c in '...')`，禁止 `re.search(r'[标点]', text)`
- **JSON 提取**：用 `json.JSONDecoder.raw_decode` 或括号深度计数，禁止 `re.search(r'\{.*\}', text)`

### 3.5 异常处理纪律

**严禁裸 `except:` 或 `except Exception: pass` 吞掉异常。**

强制执行：
- 必须捕获具体异常类型（`except ValueError`、`except json.JSONDecodeError` 等）
- 必须记录异常信息（`_logger.warning` 或 `_logger.debug`），让问题可追踪
- 确实需要忽略的场景（如清理临时文件），也必须在 `except` 块中记录 `_logger.debug`

### 3.6 全局变量单例纪律

**使用模块级全局变量实现单例时，必须用 `threading.Lock` 保护双重检查锁定。**

正确写法：
```python
_instance = None
_lock = threading.Lock()

def get_instance():
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MyClass()
    return _instance
```

### 3.7 关键调试数据落库纪律（新增）

**任何异步判定系统（Judge、审核、质检）的原始响应必须落库或落日志，严禁只存解析后的结果。**

今天教训：
- judge 只存了解析后的 score/reason/dimensions，没存原始 LLM 响应
- 出现空 reason 时无法复盘 → 不知道模型是漏了字段还是输出了自然语言
- 添加 `judge_raw_response` 字段后，空 reason 问题才能定位到"模型输出的是分析文本而非 JSON"

强制执行：
1. 异步判定系统的原始响应必须存储（tick_log 字段或独立日志文件）
2. 存储时截断到合理长度（如 4000 字符），避免数据库膨胀
3. 解析失败时必须把原始响应一起记录到日志

---

### 3.8 审计与排查输出结构化纪律

**进行代码审查、技术审计、问题排查或逻辑梳理时，输出必须结构化，禁止零散罗列代码片段。**

结构化要求：
1. 按模块/层次分类
2. 每个条目包含：位置、上下文（在什么流程里触发）、用途（设计意图）、评估（是否合理）、改进建议
3. 必须有总结和待办清单

今天教训：审计系统截断逻辑时，起初只是零散 grep 出代码片段甩给用户，没有交代"这是什么模块的什么逻辑、在什么流程里触发、目的是什么"，导致用户完全不知道我在说什么。

---

### 3.9 数据截断与限制纪律

**系统中新增或修改任何涉及数据丢弃、内容截断、资源限制、结果裁剪的逻辑时，必须同时满足三条标准：**

1. **可观测**：触发时必须打日志，记录原始量→截断后量、原因
2. **非粗暴**：优先用语义感知的方式（关键词定位、摘要、分层）替代硬截断（`[:N]`）
3. **可配置**：阈值必须收敛到统一配置中心，禁止散落在各处硬编码

今天教训：
- `fetch_webpage` 直接用 `text[:12000]` 截断网页正文，用户问的价格可能在第 5 屏，一刀砍了就没了
- 所有截断阈值（`max_chars=4000/6000/12000`、`max_tokens=2000/256`）散落在 10+ 个文件的硬编码中
- 大部分截断没有日志打点，出了问题无法追溯

---

### 3.10 实验幂等纪律（新增）

**实验系统（run_experiment.py）必须保持幂等，严禁在回测过程中调用任何会改变现实世界的 skill。**

实验的目的是对比不同配置下 Bot 回复质量的差异，不是让 Bot 真的去执行操作。

强制执行：
1. **只读工具白名单**：实验中允许调用的工具仅限于获取信息，包括 `browse_url`、`web_search`、`search_in_page`、`get_current_time`、`get_weather`、`stock_query`、`search_memory`、`tuya_list_devices`
2. **写操作工具黑名单**：严禁在实验中调用 `tuya_control_device`（控制设备开关）、`tuya_set_temperature`（设置温度）等任何会改变设备状态的工具
3. **工具过滤机制**：`generate_reply` 必须在注册工具后，从注册表中删除黑名单工具，再把剩余的只读工具传给 LLM
4. **如果实验需要测试工具调用效果**：使用 mock/stub 代替真实调用，绝不能用真实设备做实验

今天教训：
- 当前 `generate_reply` 完全不传 `tools`，导致实验中的 Bot 和真实 Bot 行为严重不符（真实 Bot 会调用工具查询信息，实验 Bot 纯靠记忆瞎猜）
- 但未来如果直接传入完整 tools 列表，又可能在回测时意外打开灯、调高空调温度，改变现实世界

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

### 4.7 汇报必须交代完整上下文

**汇报任何技术发现、代码行为或系统机制时，必须完整交代三要素，禁止只抛出结论或代码片段。**

三要素：
1. **上下文**：在哪个模块、哪个函数、哪段代码里？
2. **背景**：在什么流程、什么时机、什么条件下触发？
3. **用途**：设计意图是什么？为了解决什么问题？有什么副作用？

今天教训：汇报 `max_messages=200` 时只说"这会把正确时间戳的历史冲掉"，没有解释这是什么模块的什么逻辑、在什么流程里触发、为什么要做这个限制，导致用户完全不知道我在说什么。

---

### 4.8 发现隐藏机制必须主动揭示

**发现用户可能未知的系统行为（隐藏配置、副作用、魔法数字、遗留代码、隐式截断、状态变更）时，必须主动揭示并确认用户是否知情，禁止默认用户已知。**

揭示格式：
> 我在 `<位置>` 发现了一个 `<机制>`，它的作用是 `<用途>`，你是否知情？

今天教训：代码里存在大量用户不知道的截断逻辑（`max_messages=200`、各种 `max_chars`、死代码等），默认用户"应该知道"，结果用户完全不知情。

---

### 4.9 用户指出缺陷时先理解预期再改进

**用户指出方案、逻辑或实现有缺陷时，必须先充分理解用户的预期方式，明确更好的替代方案后再实施改进，禁止在未明确用户意图前擅自修改。**

今天教训：用户指出"从头截断太粗暴"后，起初只是简单认同，没有追问"更好的方式是什么"，直到用户自己提出"关键字上下文截取"——这个思路远比"用模型做摘要"更直接、更有效。

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
| 未测量 Judge 实际耗时（25s）就降 timeout 到 15s | 大量 timeout → 中性分 fallback → 实验结果仍不准 | **回滚 + 书面报告 + 守则更新** |

---

## 对话结束自检

每次对话结束前，必须逐项确认：
1. 本次是否有**未经同意**的修改？
2. 本次是否有**超出范围**的修改？
3. 本次是否有**隐瞒或美化**结果？
4. 本次是否有**偏离用户指令**的行为？

**如有任何一项为"是"，必须立即向用户书面报告并请求处理。**
