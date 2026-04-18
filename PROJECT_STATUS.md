# 微信 Mac RPA 项目进度

## 更新时间
2026-04-15 10:45

## 当前状态
- ✅ 项目架构：Vision OCR 视觉识别方案（L1-L5 模块化已完成）
- ✅ 微信运行（版本 4.1.8）
- ✅ OCR 识别正常
- ✅ LLM 连接正常
- ✅ 消息发送正常
- ✅ 登录恢复：支持自动点击登录按钮并恢复主窗口
- ✅ 模块化实现（`wechat_rpa/`）全部完成：Capture / OCR / Layout / Message / VisionPipeline / Session / Reply / Action / Bot
- ✅ 真实场景回归测试已建立（`test_real_scene_extraction.py`）
- ⏳ 昵称识别准确率仍需优化
- ⏳ 多显示器场景支持

## 最近修复

### error_20260413_001 - 聊天名称识别错误 ✅ 已修复
- **问题**: 聊天名称 "W1han" 被错误识别为 "®v QS."
- **原因**: 标题栏识别范围 `TITLE_Y_MAX = 60` 太宽泛，包含窗口控制按钮区域
- **修复**: 
  - 收紧 Y 范围: 60 → 50
  - 添加 X 范围过滤: `TITLE_X_MAX_RATIO = 0.70`
  - 过滤特殊字符: ®、©、™、QS
- **验证**: 9/9 测试通过

---

## 技术方案

### 当前方案：Vision OCR（推荐）
```
消息接收: Vision OCR 识别微信界面截图
消息发送: AppleScript + System Events  
大模型: Kimi
```

**优点**:
- 无需关闭 SIP
- 无需获取 db_key
- 不依赖微信数据库
- 更安全稳定

---

## 机器人版本

### 新架构模块化版（当前唯一版本）
```bash
cd ~/wechat-mac-rpa
python3 -m wechat_rpa.bot.wechat_bot
# 或运行集成测试
python3 tests/test_integration.py
```
- L1-L5 模块化架构（`wechat_rpa/`）
- 支持自动登录恢复（`WeChatLoginHandler`）
- 真实场景回归测试覆盖

### Accessibility API 版
```bash
./run_auto_accessibility.sh
```
- 需要辅助功能权限
- 更精确的界面控制

### 历史版本（已删除）
- `core/auto_bot_ocr_v2.py` - 已删除
- `core/auto_bot_ocr_v3.py` - 已删除
- `core/auto_bot_ocr_v4.py` - 已删除（由新架构完全替代）

---

## 关键文件

### 可直接运行版本
| 文件 | 说明 |
|------|------|
| `core/auto_bot_vision_ocr_v3.py` | ⭐ OCR V3 机器人（推荐） |
| `core/auto_bot_vision_ocr_v2.py` | OCR V2 增强版 |
| `core/wechat_layout_analyzer.py` | 布局分析器 |
| `scripts/view_ocr_history.py` | 查看识别历史 |
| `utils/llm_client.py` | Kimi LLM 客户端 |

### 模块化架构（按 `ARCHITECTURE.md` 拆分）
| 文件 | 说明 |
|------|------|
| `wechat_rpa/perception/vision_pipeline.py` | L3.5 视觉感知管道 |
| `wechat_rpa/session/chat_session.py` | L4 会话与去重 |
| `wechat_rpa/reply/policy.py` | L4 回复决策 |
| `wechat_rpa/action/message_sender.py` | L4 消息发送 |
| `wechat_rpa/bot/wechat_bot.py` | L5 主循环编排 |
| `wechat_rpa/logging/bot_logger.py` | 运行时日志 |
| `wechat_rpa/storage/chat_history.py` | 聊天记录持久化 |

---

## 历史截图存档
```
~/wechat-mac-rpa/data/screenshots/   # 当前项目统一路径
/tmp/wechat_screenshots/             # V2 历史兼容路径
├── wechat_20250411_204538_123.png
├── wechat_20250411_204541_456.png
└── ...
```

---

## 注意事项

1. **微信窗口需要可见** - OCR 需要截图
2. **授予辅助功能权限** - 系统设置 → 隐私与安全 → 辅助功能
3. **避免高频发送** - 建议间隔 3-5 秒

---

## 废弃方案

### 数据库解密方案（不再使用）
```
原方案: 解密微信 SQLite 数据库读取消息
状态: 已废弃
原因: 需要关闭 SIP + 获取 db_key，过于复杂
```

---

**状态：✅ OCR 方案运行正常，无需 db_key**
