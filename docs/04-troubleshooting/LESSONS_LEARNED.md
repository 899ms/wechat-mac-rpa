# 微信 Mac RPA 项目经验教训

> 记录开发过程中的关键问题和修复方案，避免重复踩坑

---

## 一、OCR 识别与解析

### 1.1 标题栏识别范围必须精确

**问题**: `title_y_max` 太宽泛，把窗口控制按钮（®、(S.）识别成聊天名称，导致 "W1han" → "®v QS."

**修复**:
```python
title_y_max = 95          # 覆盖 y=90 的标题，排除 y≥100 的消息区
title_x_max_ratio = 0.95  # 排除右侧图标区域
```

**原则**: 标题栏识别宁窄勿宽，必须排除窗口装饰元素。修复后添加回归测试 `test_regression_title_y_max_extracts_chat_name` 确保 y=90 的标题能被捕获。

### 1.2 输入框和消息区可以用 y 坐标精确分割

**问题**: `input_y_min` 设置得太宽松，把输入框内容误识别为消息。

**修正认知**:
- ✅ **y 坐标完全可以区分输入框**。微信 Mac 版输入框固定在底部区域
- ❌ 之前说"不能用 y 坐标"是错的——不是不能，而是阈值设错了

**修复**:
```python
input_y_min = 1040  # 输入框顶部边界（按 LayoutProfile 配置）
```

**同时注意**:
- y 坐标过滤解决**输入框残留**问题
- **已发送的消息**（如循环产生的"aaaa"）在消息区（y < 1160），要靠**去重机制**解决
- 这是两个不同的问题，不能混为一谈

### 1.3 时间戳过滤必须严格

**问题**: OCR 把时间戳（"00:04", "昨天 23:31", "星期六"）识别为消息，打乱消息序列。

**修复**:
```python
TIMESTAMP_PATTERNS = [
    r'^\d{2}:\d{2}$',
    r'^昨天\s*\d{1,2}:\d{2}$',
    r'^星期[一二三四五六日]$',
]
```

---

## 二、消息发送

### 2.1 中文输入法下 "Command+A" 会产生乱码

**问题**: V4 发送消息前用 `keystroke "a" using command down` 全选，在中文输入法下 "a" 被输入成拼音，产生 "laayaua5aapangaaaaa~" 等乱码。

**根因**: `keystroke` 在中文输入法下会先触发输入法，而不是快捷键。

**修复**: 去掉全选，直接像 V2 一样用 `pbcopy + Command+V` 粘贴：
```python
subprocess.run(['pbcopy'], input=text.encode('utf-8'), timeout=2)
# 然后 AppleScript: keystroke "v" using command down
```

**原则**: 避免在中文输入法环境下用 `keystroke` 输入任何字母字符。

### 2.2 没有去重机制会导致循环发送

**问题**: 机器人发送消息后，下一轮 OCR 识别到刚发的消息，再次触发回复，形成死循环。

**修复**:
```python
# 发送后记录内容与时间、估计Y坐标
self.sent_messages.append(SentMessage(text=text, sent_at=time.time(), approx_y=approx_y))

# 下轮识别时回声检测：时间窗口优先（10s内），Y坐标辅助
def _is_echo(self, identity, sent):
    text_match = sent.text in msg.text or msg.text in sent.text
    time_match = (time.time() - sent.sent_at) < 10.0
    y_match = abs(sent.approx_y - identity.approx_y) < 80
    return text_match and time_match and y_match
```

**原则**: 任何自动回复系统必须有**内容+位置+时间**的多维去重，不能仅靠字符串包含或时间戳。聊天滚动时 Y 坐标会变化，因此时间窗口是回声检测的首要条件。

### 2.3 冷却期是必要的，但不能替代去重

**问题**: 仅靠 30 秒冷却期无法阻止循环——30 秒后仍会识别到自己的消息。

**原则**: 冷却期和去重是双重保护，缺一不可。

---

## 三、代码与架构

### 3.1 不要重复造轮子，已有 V2 直接用

**问题**: V4 重新实现了发送逻辑，加了不必要的全选操作，引入了 V2 没有的问题。

**教训**:
- V2 的 `pbcopy + Command+V` 方案已经验证稳定
- 重构时不要轻易改动底层稳定模块
- 如果 V2 能用，优先复用而不是重写

### 3.2 修复要治本，不要堆补丁

**反模式**:
- ❌ "过滤特殊字符 ®"
- ❌ "跳过超长乱码消息"
- ❌ "添加置信度阈值"

**正解**:
- ✅ 找到乱码产生的根因（输入法 + keystroke）
- ✅ 从根因上修复（改用 pbcopy）

### 3.3 模块化不等于没有依赖

**问题**: V4 的 parser 和 storage 各自独立，但去重逻辑跨了多个模块，导致循环发送。

**原则**: 业务逻辑（如循环检测）必须放在 bot 的 orchestration 层，而不是拆到各个模块里。

---

## 四、测试

### 4.1 测试必须验证准确性，不是"能跑通"

**错误标准**:
- ❌ "解析成功，返回了 6 条消息"
- ❌ "没有抛异常"

**正确标准**:
- ✅ 聊天名称准确率 >= 95%
- ✅ 发送者类型识别率 >= 90%
- ✅ 时间戳过滤率 = 100%
- ✅ 输入框残留过滤率达标

### 4.2 错误截图必须立即归档为测试用例

**问题**: 早期没有系统保存错误截图，导致修复后无法回归验证。

**修复**: 建立 `tests/fixtures/errors/` 目录，每个错误包含：
- `error_XXX.png`: 原始截图
- `error_XXX.json`: 期望结果 + 问题描述

### 4.3 测试用例必须包含预期数据

**问题**: 批量导入 20 张截图时，很多用例缺少 `expected` 数据，只能验证"不报错"。

**原则**: 每个测试用例必须有完整的期望输出，包括聊天名称、消息列表、发送者类型。

---

## 五、快速参考

### 启动自动模式
```bash
cd ~/wechat-mac-rpa
python3 -m wechat_rpa.bot.wechat_bot
```

### 关键文件
| 文件 | 说明 |
|------|------|
| `wechat_rpa/bot/wechat_bot.py` | 当前唯一入口（L1-L5 模块化架构） |
| `wechat_rpa/parser/wechat_parser.py` | 当前模块化实现中的解析器 |
| `wechat_rpa/action/reply_generator.py` | 当前模块化实现中的回复策略与生成器 |
| `tests/fixtures/errors/` | 错误用例库 |
| `wechat_rpa/tests/test_modules.py` | 模块化单元测试 |
| `docs/02-architecture/ARCHITECTURE.md` | 目标重构架构设计（与当前 `wechat_rpa/` 结构存在差异） |

### 发送消息的正确方式
```python
subprocess.run(['pbcopy'], input=text.encode('utf-8'), timeout=2)
# AppleScript: keystroke "v" using command down + return
```

---

**更新时间**: 2026-04-19
**状态**: 模块化架构运行稳定，已解决循环发送和乱码问题；架构文档已同步更新去重机制（时间窗口优先 + MessageIdentity）
