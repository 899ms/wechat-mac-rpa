
## 2026-04-13 - 修复 error_20260413_001 (聊天名称识别错误)

### 问题
- 聊天名称 "W1han" 被错误识别为 "®v QS."
- 原因: 标题栏识别范围 `TITLE_Y_MAX = 60` 太宽泛，包含窗口控制按钮区域和右侧图标

### 修复方案
1. **收紧标题栏 Y 范围**: `TITLE_Y_MAX` 60 → 50
2. **添加 X 范围过滤**: 新增 `TITLE_X_MAX_RATIO = 0.70`，排除右侧图标区域（搜索、电话按钮等）
3. **特殊字符过滤**: 排除包含 ®、©、™、QS 等明显非昵称字符的元素

### 代码变更
```python
# src/parser/wechat_parser.py
TITLE_Y_MAX = 50           # 收紧
TITLE_X_MAX_RATIO = 0.70   # 新增

# _parse_chat_area 方法中
title_x_max = self.image_width * self.TITLE_X_MAX_RATIO
title_elems = [e for e in elements if e.y < self.TITLE_Y_MAX and e.x < title_x_max]

# 过滤特殊字符
filtered = [e for e in title_elems if not any(c in e.text for c in ['®', '©', '™', 'QS'])]
```

### 验证结果
- error_20260413_001.png: 识别正确 "W1han" ✓
- private_w1han.png: 识别正确 "W1han" ✓
- 全量测试: 9/9 通过 ✓

### 状态
- 错误样本状态: fixed
- 修复时间: 2026-04-13 06:40
