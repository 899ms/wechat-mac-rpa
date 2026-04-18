# 微信 RPA V2.0 - 增强功能说明

## 新增功能

### 1. 多对话管理 ✅
```python
# 每个聊天对象独立会话
sessions = {
    "群聊A_ID": ChatSession("群聊A"),
    "群聊B_ID": ChatSession("群聊B"),
    "联系人C_ID": ChatSession("联系人C"),
}
```

**效果**：
- 识别当前聊天对象名称（顶部标题栏）
- 不同群聊/私聊有独立的对话历史
- 互不干扰

### 2. 发言人识别 ⚠️ 部分支持

| 场景 | 识别能力 | 说明 |
|------|---------|------|
| 私聊 | ✅ 完美 | 左=对方，右=自己 |
| 群聊-方向 | ✅ 可用 | 左=群友，右=自己 |
| 群聊-昵称 | ⚠️ 有限 | 受OCR精度限制 |

**限制原因**：
- 微信昵称显示在消息上方，字体小，OCR 容易漏识别
- 昵称和消息内容在坐标上有重叠
- 需要更复杂的图像分析（颜色/字体区分）

### 3. @检测 ✅
```python
if "@W1han" in message:
    priority_reply = True  # 优先回复
```

### 4. 对话上下文隔离 ✅
```python
# 群聊A的历史
sessionA.history = [
    {"role": "user", "sender": "张三", "content": "你好"},
    {"role": "assistant", "content": "你好！"},
]

# 群聊B的历史（独立）
sessionB.history = [
    {"role": "user", "sender": "李四", "content": "今天天气"},
    {"role": "assistant", "content": "今天晴天"},
]
```

### 5. 历史截图保存 ✅
> 注：V2 版本默认保存到 `/tmp/wechat_screenshots/`。当前项目统一数据目录为 `~/wechat-mac-rpa/data/screenshots/`。
```
/tmp/wechat_screenshots/             # V2 默认路径
~/wechat-mac-rpa/data/screenshots/   # 当前项目统一路径
├── wechat_20250411_204538_123.png
├── wechat_20250411_204541_456.png
└── ...
```

## 使用方式

```bash
# 启动 V2
python3 core/auto_bot_vision_ocr_v2.py

# 查看历史识别记录
python3 scripts/view_ocr_history.py

# 导出日志
python3 scripts/view_ocr_history.py export
```

## 当前局限

1. **群聊发言人精确识别**：需要更高精度的 OCR 或图像分割
2. **多窗口切换**：当前只处理最前面的微信窗口
3. **群聊人数显示**：可以识别 "（5）" 但无法获取完整成员列表

## 对比 V1 vs V2

| 功能 | V1 | V2 |
|------|----|----|
| 基本对话 | ✅ | ✅ |
| 多聊天对象管理 | ❌ | ✅ |
| 对话历史隔离 | ❌ | ✅ |
| 发言人方向判断 | ✅ | ✅ |
| 发言人昵称识别 | ❌ | ⚠️ 有限 |
| @检测 | ❌ | ✅ |
| 历史截图保存 | ❌ | ✅ |
| 会话统计 | ❌ | ✅ |
