# Tick 例行排查指南

> 本文档记录排查 tick debug 数据的标准流程，基于 2026-04-19 的实战经验。

---

## 一、排查前准备

### 1.1 确认代码版本

```bash
cd ~/wechat-mac-rpa
git log --oneline -3
```

- 若 Bot 进程已运行超过代码修改时间，**先重启 Bot** 再排查：
  ```bash
  pkill -f "python3 run_bot.py"
  cd ~/wechat-mac-rpa && nohup python3 run_bot.py > /tmp/bot_run.log 2>&1 &
  ```

### 1.2 确认 Bot 运行状态

```bash
ps -p $(pgrep -f "python3 run_bot.py") -o lstart,etime,cmd 2>/dev/null || echo "Bot 未运行"
```

### 1.3 查看实时日志

```bash
tail -f /tmp/bot_run.log
```

---

## 二、标准排查流程（5 步）

### Step 1: 列出最近 tick，观察文件大小分布

```bash
ls -lt data/debug/*.json | head -20
```

**异常模式识别：**

| 文件大小 | 含义 | 可能问题 |
|---------|------|---------|
| ~2 KB | OCR 为空，只有 clusters 旧数据 | WeChat 未就绪 / 截图失败 |
| ~9 KB | 少量 OCR，少量 candidates | 聊天窗口未打开 / 只有历史消息 |
| ~17 KB | 完整 OCR，大量 candidates | 正常截图，需进一步分析提取结果 |

### Step 2: 检查 action 分布

```bash
ls -1t data/debug/*.json | head -100 | while read f; do
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); a=d.get('action',''); print(f'{a!s:20s} {sys.argv[1]}')" "$f"
done | sort | uniq -c | sort -rn | head -10
```

**预期 vs 异常：**
- 正常：`none` 占多数（无未读时），偶尔有 `switch:<聊天名>` 或 `send:<内容>`
- 异常：连续 100+ 个 `none` 且无不读 → 检查 switch 过滤逻辑
- 异常：有 `send` 但 `chat_name=''` → 检查 title_y_max 配置

### Step 3: 检查 Bot 决策字段

```bash
ls -1t data/debug/*.json | head -100 | while read f; do
  python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print(f'should_reply={d[\"bot_should_reply\"]!s:5s} new_msgs={d[\"bot_new_messages_count\"]!s:3s} '
      f'chat_name={d[\"bot_chat_name\"]!r:20s} action={d[\"action\"]!r:15s} '
      f'switch_reason={d[\"bot_switch_reason\"]!r:30s} {sys.argv[1]}')
" "$f"
done | sort | uniq -c | sort -rn | head -10
```

**关键字段含义：**

| 字段 | 正常值 | 异常值 | 排查方向 |
|------|--------|--------|---------|
| `chat_name` | 非空字符串 | `''` | `title_y_max` 过小 / title 识别失败 |
| `new_messages_count` | ≥0 | 始终 0 | 消息提取失败 / 会话去重过于激进 |
| `should_reply` | True/False | 始终 False | Policy 过滤 / 群聊缺少 @ |
| `switch_reason` | `未读 N` / `无未读项` | `chat_list_items 为空` | 聊天列表解析失败 |

### Step 4: 分析聊天列表未读分布

```bash
ls -1t data/debug/*.json | head -100 | while read f; do
  python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
unread = d.get('layout_chat_list_unread',[])
has_unread = any(u and u!='0' for u in unread)
print(f'{has_unread!s:5s} unread={unread!r:50s} nicknames={d.get(\"layout_chat_list_nicknames\",[])}')
" "$f"
done | sort | uniq -c | sort -rn | head -10
```

**注意免回复列表过滤：**
```python
no_reply_chats = {"腾讯新闻", "文件传输助手"}
```

即使 `unread` 显示有数字，若对应 nickname 在免回复列表中，switch 不会触发。

### Step 5: 深度分析单个异常 tick

如果你已经通过 Step 1-4 定位到一个具体异常 tick，**不要直接写脚本分析**，先对照 **TROUBLESHOOTING.md** 的 §2 症状速查表：

1. **加载 tick JSON** 确认字段完整性
2. **对照症状速查表**（A-F）定位问题类别
3. **按速查表指引的 §3 深度验证方法** 确认根因
4. 如果速查表未匹配，运行 **§4 全面数据提取脚本**

> 完整诊断流程、症状速查表、验证脚本见 `docs/04-troubleshooting/TROUBLESHOOTING.md`

---

## 三、常见问题速查表

### 3.1 chat_name 始终为空

**症状：** `bot_chat_name=''`，日志报"聊天名为空"

**根因：** `title_y_max` 配置值小于实际标题元素 y 坐标。

**排查命令：**
```python
d = json.load(open('data/debug/<tick>.json'))
for e in d['ocr_elements']:
    if 80 <= e['center']['y'] <= 140 and e['center']['x'] > 400:
        print(f'"{e["text"]}" y={e["center"]["y"]}')
# 若 y > title_y_max（默认 95），则会被过滤
```

**修复：** 调整 `wechat_rpa/layout/profile.py` 中的 `title_y_max`。

### 3.2 messages 为空但 clusters 有数据

**症状：** `extraction_messages=[]`，`extraction_clusters=N`

**排查步骤：**
1. 检查 `extraction_messages`（不是 `extracted_messages`）
2. 若确实为空，检查 `_is_noise_candidate` 过滤是否过严
3. 检查 `used_self` 是否消耗了所有 candidates

### 3.3 连续 100+ tick 无 action

**症状：** 所有 tick `action='none'`，`switch_reason='无未读项'`

**排查：**
1. 检查 unread 分布（Step 4）
2. 若唯一未读是 `腾讯新闻`/`文件传输助手` → **预期行为**（免回复过滤）
3. 若所有 unread 为空 → 确实没有新消息

### 3.4 OCR 为空但 clusters 有旧数据

**症状：** `ocr_elements=[]`，`extraction_clusters>0`

**根因：** 截图失败（WeChat 未就绪），但 debug JSON 保留了上一 tick 的 clusters。

**处理：** 非代码 bug，检查 WeChat 窗口状态。

### 3.5 debug JSON 中 screenshot_path 指向 /tmp 而非 data/screenshots

**症状：** `screenshot_path` 为 `/tmp/wechat_capture_xxxx.png`，无法直接关联到 `data/screenshots/` 下的实际截图

**根因：**
- 旧代码：WindowCapture 使用固定 `/tmp/wechat_capture.png`，每次覆盖
- 已修复：WindowCapture 生成唯一临时文件名，Bot 保存后更新路径

**排查关联截图的方法：**
```bash
# 根据 tick 时间戳找截图
tick_time="2026-04-19T09-05-32"
ls data/screenshots/*$(echo $tick_time | tr '-' '' | tr ':' '')*.png
```

---

## 四、本次排查案例（2026-04-19）

### 4.1 发现的问题

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 1 | `chat_name` 始终为空 | `title_y_max=50` 过滤了 y=90 的标题 | `title_y_max=95` |
| 2 | 最近 100 tick 无 action | 唯一未读是"腾讯新闻"（免回复列表） | 预期行为，无需修复 |
| 3 | tick 7200-7204 OCR 为空 | WeChat 窗口未就绪 | 预期行为 |

### 4.2 排查时间线

1. **列出 tick 大小分布** → 发现 1969/9617/16693 三种模式
2. **检查 action 分布** → 100 个 tick 全为 `none`
3. **检查 Bot 决策字段** → `chat_name=''`，`switch_reason='无未读项'`
4. **分析聊天列表** → `unread=['','','1','','','','']`，对应 `腾讯新闻`
5. **深度分析 tick 7213** → 发现 `layout_title_elements=[]`，但 OCR 有 `"王芊 @ai开发小分队" y=90`
6. **定位 title_y_max=50 过小** → 修复为 95
7. **验证 Bot 进程** → PID 22529 启动于 4/18 22:55，运行旧代码未重启

### 4.3 回归测试

新增 fixture：`tests/fixtures/regression_title_y90_20260419.png`

新增测试：
- `test_regression_title_y_max_extracts_chat_name`（LayoutParser）
- `test_no_switch_when_only_no_reply_chats_have_unread`（Bot）
- `test_switch_to_highest_unread_non_no_reply_chat`（Bot）
