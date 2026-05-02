# 开发守则 —— 禁止临时修补式假设

> 本守则记录从项目中吸取的教训，防止"为测试临时通过而写假设"的错误做法反复发生。

---

## 红线 1：阈值必须有出处，且变更必须同步文档

**禁止在代码中直接写魔法数字。**

❌ 错误：
```python
red_pixels >= 50          # 为什么 50？
confidence < 0.4          # 为什么 0.4？
y > 900                   # 为什么 900？
left_boundary + 220       # 为什么 220？
```

✅ 正确：
```python
# 基于 N=50 个样本的 P95 值，TODO: 持续校准
red_pixels >= profile.badge_min_pixels
```

如果必须硬编码，注释中必须写明数据来源和校准 TODO。

**额外要求**：当修改 `LayoutProfile` 中的任何阈值（如 `title_y_max`、`input_y_min`、`left_boundary` 等）时，必须同时执行：
1. `grep -rn "old_value" docs/` 找出所有文档中的旧数值引用
2. 同步更新 `LESSONS_LEARNED.md`、`PROJECT_STATUS.md`、`TROUBLESHOOTING.md` 等归档文档
3. 更新相关回归测试的 fixture 和预期值

**原因**：参数会经历多轮调优（如 50 → 60 → 95），如果只改代码不改历史文档，归档文档会变成"考古层"，记录的是中间态而非最终态，导致后续排查时产生误判。

---

## 红线 2：拒绝"列表式补丁"

**当你发现自己在维护一个不断增长的列表时，停下来问自己：这是治本还是治标？**

❌ 错误：
```python
THINKING_PREFIXES = ["等等，", "让我想想", ...]      # 还会增长
no_reply_chats = {"腾讯新闻", "文件传输助手"}          # 还会增长
noise_items = ["®v", "®0", "QS.", ...]                # 还会增长
```

✅ 正确：
向上游走一步，解决产生异常的根本原因：
- 思考内容 → 用 API 参数让模型不输出，而不是事后过滤
- 免回复账号 → 从配置文件读取，或通过 UI 特征（头像角标）识别
- OCR 噪声 → 用区域掩码排除，而不是用正则清洗

---

## 红线 3：测试是探针，不是遮瑕膏

**严禁在测试代码中为掩盖产品缺陷而添加 mock 修正。**

❌ 错误：
```python
OCR_ERROR_MAP = {"Al 助手": "AI 助手"}   # 测试里修 OCR 错误
```

✅ 正确：
测试失败 → 修产品代码（OCR 引擎、布局解析器）→ 测试通过。

---

## 红线 4：一 bug 一 fixture，不篡改数据

**禁止在测试中修改 fixture 数据来伪造场景。**

❌ 错误：
```python
perception.messages[-1] = other_msgs[-1]   # 暴力修改
for m in perception.messages:
    m.sender_type = SenderType.SELF          # 全部改成自己
```

✅ 正确：
为每种场景创建独立的 fixture 截图 + JSON 预期文件，fixture 视为只读档案。

---

## 红线 5：用区域掩码代替文本启发式

**当 OCR 从错误区域读出文本时，排除该区域比用正则清洗文本更可靠。**

❌ 错误：
```python
if text.isdigit() or re.match(r"^[\d\s]+$", text):
    return True   # 事后猜测这是步数数字
```

✅ 正确：
```python
# 在 LayoutParser 层：头像区域内的 OCR 结果整体丢弃
avatar_mask = detect_avatar_regions(image)
if avatar_mask.contains(elem.center):
    return True
```

---

## 红线 6：分辨率无关原则

**所有像素坐标必须相对于 LayoutProfile 或实际图像尺寸。**

❌ 错误：
```python
y > 900
x > 1150
return self.center.x / 1760   # 硬编码分辨率
```

✅ 正确：
```python
y > profile.input_y_min - 50
x > profile.left_boundary + profile.avatar_width
return self.center.x / image_width
```

---

## 红线 7：启发式必须可退化（Graceful Degradation）

**当启发式不确定时，选择保守策略，由策略层统一决策。**

❌ 错误：
```python
if any(p in text for p in thinking_patterns):
    return "收到"   # 宁杀错不放过，直接丢弃全部内容
```

✅ 正确：
```python
# 置信度打分，0~1，由策略层决策
confidence = classify_thinking(text)
if confidence > 0.9:
    return "收到"
# 否则保留，让下游处理
```

---

## 红线 8：定期复盘"补丁密度"

**如果某个文件的过滤/清洗逻辑持续增长、越来越复杂，这是架构腐烂的信号。**

应定期问自己：
- 这个文件里有多少条正则？
- 有多少个硬编码列表？
- 有多少个魔法数字？

当数量超过 3 个时，必须停下来重构，将补丁升级为通用机制。

---

## 红线 9：关键路径必须留痕（日志即证据）

**每个可能导致"为什么跳过/为什么执行"的决策点，必须留下结构化日志。**

❌ 错误：
```python
if diff < threshold:
    return None   # 静默跳过，无从排查

result = api_call(image)   # 成功/失败都不记录
messages = convert(result)  # 转换前后数量对不上，不知道在哪丢的
```

✅ 正确：
```python
_logger.info(
    f"[SmartPipeline] 像素差异: {diff:.6f} "
    f"(阈值={threshold}), 决策={'跳过API' if skip else '调用API'}"
)
if skip:
    _logger.info(f"[SmartPipeline] 本地跳过统计: skip={skip_count}, api={api_count}")
    return None

t0 = time.time()
try:
    result = api_call(image)
    _logger.info(f"[SmartPipeline] API成功: latency={(time.time()-t0)*1000:.0f}ms, msgs={len(result)}")
except Exception as e:
    _logger.error(f"[SmartPipeline] API失败({(time.time()-t0)*1000:.0f}ms): {e}")
    return fallback(image)

messages = convert(result)
_logger.info(f"[SmartPipeline] 消息转换: input={len(result)} → output={len(messages)}")
for i, m in enumerate(messages):
    _logger.debug(f"  msg[{i}] sender={m.sender} text='{m.text[:40]}...'")
```

**日志规范 checklist：**
1. **决策点必记录**：任何 if/else 分支，特别是"跳过"路径
2. **外部调用必记录**：API 调用前后（开始时间、结束时间、latency、成功/失败）
3. **数据转换必记录**：输入数量 vs 输出数量（方便定位丢数据的位置）
4. **统计信息定期记录**：累计 skip 率、API 调用次数、fallback 次数
5. **使用结构化前缀**：`[模块名] ` 前缀，方便 grep 过滤
6. **关键数据脱敏预览**：文本内容记录前 40 字预览，不要记录完整消息（隐私）
7. **异常必须带上下文**：不只是 `logger.error(e)`，要包含当时的决策参数

**为什么重要**：当线上出现"为什么这条消息没有触发回复"或"为什么多回复了一次"时，没有日志只能猜，有日志 30 秒内定位。

---

## 历史教训

### 教训 1：`_is_likely_nickname` 误杀短消息
用 `len(text) < 2 or len(text) > 20` 判断昵称，导致"怎么"、"在吗"、"你好"被当作昵称跳过，**漏回**。

### 教训 2：`_normalize_chat_name` 未清洗数字前缀
`"10 10 王芊"` 和 `"王芊"` 分裂成两个 session，新 session 没有历史记录，**重复回复**。

### 教训 3：`red_pixels >= 50` 阈值过高
未读 badge 实际只有 25 像素，检测不到，**未读切换失效**。

### 教训 4：`_THINKING_PREFIXES` 层层叠加
过滤逻辑从简单列表发展到两级验证，仍然误杀正常回复，**思考内容混入**。

### 教训 5：`avatar_noise_x_max` 反复横跳
从 700 → 560 → 700，没有任何数据支撑，只是"试出来的"。
