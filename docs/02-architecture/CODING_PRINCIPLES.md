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
