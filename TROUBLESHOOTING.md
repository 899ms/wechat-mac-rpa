# 排查修复文档 —— 通用诊断框架

> 不基于单一 case 猜测，而是设计可复用的排查流程，逐层归因。

---

## 诊断原则

1. **截图 diff 优先**：调试 JSON 和日志可能误导（如 tick1 的 `bot_chat_name` 被覆盖为空），**截图是唯一可信的 ground truth**。任何排查必须先看截图，验证 OCR 识别到的文字是否真实存在于窗口中。
2. **分层验证**：从 Capture → OCR → 布局解析 → 消息提取 → Bot 决策，逐层对比期望/实际输出
3. **diff 驱动**：每一层找出"期望有但实际没有"或"期望没有但实际有"的元素
4. **日志先行**：在关键分支插入结构化日志，复现问题时不依赖截图猜测

### 排查流程（必须按顺序执行）

```
Step 1: 看日志 → 定位异常 tick（如"发送了不该发的消息"）
Step 2: 看截图 → 验证 OCR 结果是否真实存在（ground truth）
Step 3: 看调试 JSON → 了解 Bot 决策过程（辅助，非唯一依据）
Step 4: 分层归因 → 确定问题在哪一层（Capture/OCR/Layout/Extract/Bot）
Step 5: 修复 → 在正确层级修复，禁止跨层打补丁
```

**血的教训**：
- tick1：调试 JSON 显示 `chat_name=''`、`action='send'`，误以为 chat_name 为空时发送了消息。实际看截图后发现，提取到的 "Q Al模式" 等"消息"根本不存在于聊天窗口中 → 根因是 OCR 噪声，不是 chat_name 逻辑。
- tick81：只看调试 JSON 以为是 "10" 被当昵称。实际看布局数据后发现，"10" 和消息 x 差距 218px，不应聚类 → 根因是聚类缺少 x 差距检查。

---

## Layer 0: 输入层 —— OCR 原始输出是否完整

### 验证方法
对任意截图，输出 OCR 识别的所有元素（text + bbox + center）：

```python
elements = ocr.recognize(image_path)
for e in sorted(elements, key=lambda e: e.center.y):
    print(f"'{e.text}' x={e.bbox.x} y={e.bbox.y} cx={e.center.x} cy={e.center.y}")
```

### 期望 vs 实际对比
| 期望 | 实际缺失 | 问题归类 |
|------|---------|---------|
| 消息区应有消息文本 | 消息文本缺失 | OCR 漏识别 / 被过滤 |
| 昵称区应有昵称 | 昵称缺失 | 私聊不显示昵称（正常）/ OCR 漏识别 |
| 聊天列表应有昵称+预览 | 聊天列表项缺失 | `_parse_chat_list` 输入为空 |
| 头像附近不应有数字 | 头像数字混入消息区 | 头像噪声过滤失效 |

### 关键检查点
- **左侧聊天列表**（x < left_boundary）：是否识别到所有聊天项？
- **右侧消息区**（x ≥ left_boundary）：是否识别到所有消息？
- **标题栏**（y < title_y_max）：chat_name 来源是否干净？
- **底部噪声**（y > input_y_min）：输入法候选框是否被过滤？

---

## Layer 1: 布局层 —— 元素分组是否正确

### 1.1 聊天列表分组验证

**方法**：打印 `_parse_chat_list` 的每一步中间结果：

```
Step 1: left_elements (x < 480) = [elem1, elem2, ...]
Step 2: nick_col (x >= 150) = [候选昵称元素]
Step 3: groups (y 间距 < 50) = [[昵称+预览], [昵称+预览], ...]
Step 4: unread_for_group = ["", "1", "", ...]
Step 5: _clean_nickname 后 = ["王芊", "腾讯新闻", ...]
```

**期望 vs 实际对比**：
| 检查项 | 期望 | 实际异常 | 归因 |
|--------|------|---------|------|
| groups 数量 | = 聊天列表可见项数 | 少于实际 | `nick_col` 过滤太严格 / y 间距阈值不当 |
| group[0] | = 昵称 | = 消息预览 / 时间戳 | 分组逻辑错误 |
| unread_for_group | 有 badge 的位置为数字 | 无 badge 的位置有值 | OCR 误检 / 颜色检测误检 |
| unread_for_group | 有 badge 的位置为空 | badge 未识别 | ROI 位置错误 / 颜色条件错误 |

### 1.2 消息区聚类验证

**方法**：打印 `_extract_other_messages` 的聚类结果：

```
clusters = [[elem1, elem2], [elem3], ...]
for i, c in enumerate(clusters):
    gap = c[1].center.y - c[0].center.y if len(c) > 1 else "N/A"
    in_nick_range = x_min <= c[0].center.x <= x_max
    print(f"cluster {i}: {[e.text for e in c]}, gap={gap}, in_nick_range={in_nick_range}")
```

**期望 vs 实际对比**：
| 检查项 | 期望 | 实际异常 | 归因 |
|--------|------|---------|------|
| cluster 数量 | = 消息条数（+ 昵称） | 过多 | threshold 太小，把多行文本拆散 |
| cluster 数量 | = 消息条数（+ 昵称） | 过少 | threshold 太大，把多条消息合并 |
| cluster[0] 为昵称 | gap > 30px 且 in_nick_range | gap <= 30px 但被当昵称 | 阈值缺失，无条件把 cluster[0] 当昵称 |
| cluster[0] 为消息 | gap <= 30px 或 !in_nick_range | gap > 30px 但被当消息 | 阈值过高 |

---

## Layer 2: 提取层 —— 消息内容是否完整

### 验证方法
对比 OCR 原始输出和最终提取的 messages：

```python
# OCR 中右侧消息区所有文本
ocr_texts = [e.text for e in elements if e.center.x > left_boundary]

# 提取结果中的所有文本
extracted_texts = [m.text for m in result.messages]

# 找差异
missing = [t for t in ocr_texts if t not in extracted_texts]
extra = [t for t in extracted_texts if t not in ocr_texts]
```

**期望 vs 实际对比**：
| 检查项 | 期望 | 实际异常 | 归因 |
|--------|------|---------|------|
| missing | 空 | 有短文本 | 被 `_is_avatar_noise` 过滤 / 被当昵称吞掉 |
| missing | 空 | 有长文本 | 被 `_is_system_notice` 误判 / 聚类错误 |
| extra | 空 | 有噪声 | `_is_noise_candidate` 未过滤 / 聊天列表元素混入 |
| sender | 昵称或"对方" | = "对方"（群聊中） | 昵称未识别（聚类失败） |

---

## Layer 3: Session 层 —— 去重是否生效

### 验证方法
打印 Session 的 key 和 `seen_messages`：

```python
session = bot._get_session(chat_name)
print(f"session key: {chat_name}")
print(f"seen_messages: {len(session.seen_messages)}")
print(f"history: {len(session.history)}")
```

**期望 vs 实际对比**：
| 检查项 | 期望 | 实际异常 | 归因 |
|--------|------|---------|------|
| 同一聊天的 session key | 始终相同 | 出现多个 key | `_normalize_chat_name` 不一致 / `_clean_nickname` 不一致 |
| 新消息 | 被 `filter_new` 识别 | 被当作已读 | `seen_messages` 匹配失败 / 文本相似度阈值不当 |
| 已回复消息 | 不重复回复 | 重复回复 | `record_sent` 未生效 / session 分裂 |

---

## Layer 4: 决策层 —— 切换是否合理

### 验证方法
在 `_try_switch_to_unread_chat` 插入日志，打印每一步：

```python
def _try_switch_to_unread_chat(self, result):
    self.logger.info(f"[SwitchCheck] chat_name={result.chat_name}")
    self.logger.info(f"[SwitchCheck] chat_list_items={[(i.nickname, i.unread_count) for i in result.chat_list_items]}")
    
    unread_items = [...]
    self.logger.info(f"[SwitchCheck] unread_items after filter={[(i.nickname, i.unread_count) for i in unread_items]}")
    
    if not unread_items:
        self.logger.info("[SwitchCheck] NO SWITCH: no unread items")
        return
    
    self.logger.info(f"[SwitchCheck] SWITCHING TO: {target.nickname}")
```

**期望 vs 实际对比**：
| 检查项 | 期望 | 实际异常 | 归因 |
|--------|------|---------|------|
| 当前有未读消息 | 不切换 | 切换了 | `new_messages` 为空时触发切换，但消息实际存在（漏提取） |
| 当前无未读，其他有未读 | 切换到未读 | 未切换 | `no_reply_chats` 过滤 / `unread_count` 未识别 |
| 当前无未读，其他无未读 | 不切换 | 切换了 | `unread_count` 误识别 / `chat_name` 匹配失败 |
| 切换目标 | 真实未读聊天 | = "腾讯新闻" | `no_reply_chats` 未生效 |

---

## 通用排查命令

### 1. 对任意截图跑完整链路
```bash
cd /Users/yihanwang/wechat-mac-rpa
python3 -c "
from pathlib import Path
from unittest.mock import Mock
from wechat_rpa.perception.vision_pipeline import VisionPipeline
from wechat_rpa.layout.profile import PROFILE_WECHAT_MAC_1760X1280
from wechat_rpa.capture.window_capture import CaptureResult
from wechat_rpa.models.base import Rect

png = Path('$PNG_PATH')
pipeline = VisionPipeline(PROFILE_WECHAT_MAC_1760X1280)
pipeline.capture = Mock()
pipeline.capture.capture.return_value = CaptureResult(image_path=str(png), window_rect=Rect(0,0,1760,1280), scale_factor=1.0)
result = pipeline.perceive()

print('=== chat_name ===')
print(result.chat_name)
print('\n=== messages ===')
for m in result.messages:
    print(f'  [{m.sender}] {m.text}')
print('\n=== chat_list_items ===')
for i in result.chat_list_items:
    print(f'  {i.nickname} unread={i.unread_count}')
"
```

### 2. 打印 OCR 原始输出
```bash
python3 -c "
from wechat_rpa.ocr.vision_ocr import VisionOCREngine
from wechat_rpa.layout.profile import PROFILE_WECHAT_MAC_1760X1280

ocr = VisionOCREngine()
elements = ocr.recognize('$PNG_PATH')
for e in sorted(elements, key=lambda e: e.center.y):
    print(f'{e.text!r} x={e.bbox.x} y={e.bbox.y} cx={e.center.x} cy={e.center.y}')
"
```

### 3. 对比切换前后的截图序列
```bash
# 找出 chat_name 变化的相邻截图
python3 -c "
from pathlib import Path
# ... 批量分析脚本
"
```

---

## 待修复问题清单（按优先级）

| 优先级 | 问题 | 修复方案 | 状态 |
|--------|------|---------|------|
| P0 | 颜色检测 ROI 位置错误 | 头像区域直接检测，不从昵称推导 | 待修复 |
| P0 | `unread=1` 来源不明 | 在 `_parse_chat_list` 加结构化日志 | 待加日志 |
| P1 | 昵称→消息 gap 阈值缺失 | 用 `gap > 30px` 区分昵称和消息 | 待用户确认 |
| P1 | `_parse_chat_list` 在 W1han 窗口返回 0 项 | 分析 W1han 窗口 OCR 输出 | 待排查 |
| P2 | OCR 数字混入昵称 | 在 OCR 层限制 x 范围 | 待确认方案 |
