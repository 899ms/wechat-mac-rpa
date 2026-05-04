# 微信 Mac RPA 项目进度

## 更新时间
2026-05-04

## 当前状态
- ✅ 项目架构：双感知管道（SmartPerceptionPipeline 主力 + VisionPipeline 备用）
- ✅ 微信运行（版本 4.1.8）
- ✅ OCR 识别正常
- ✅ LLM 连接正常（OpenClaw/Kimi 用于回复生成，qwen3.6-flash 用于感知 API 兜底）
- ✅ 消息发送正常
- ✅ 登录恢复：支持自动点击登录按钮并恢复主窗口
- ✅ 模块化实现（`wechat_rpa/`）全部完成
- ✅ 真实场景回归测试已建立
- ✅ 智能感知管道已上线（`SmartPerceptionPipeline`：本地预判 + API 兜底，92.6% tick 无需调用 API）
- ✅ Memory 引擎集成完成
- ✅ Tool calling / Skill 匹配机制完成
- ✅ **结构化 Prompt + SessionMemory**（跨 tick 工具缓存，避免重复搜索）
- ✅ **browse_url 工具**（用户分享链接时自动提取正文）
- ✅ **web_search 结果带链接**（支持 browse_url 二次打开）
- ✅ **Hermes 深度分析路径**（skill 匹配时走 Hermes，支持 300 字/5 条回复）
- ⏳ 昵称识别准确率仍需优化
- ⏳ 多显示器场景支持
- ⏳ GitHub 推送（网络超时，待手动 push）

## 最近修复

### error_20260413_001 - 聊天名称识别错误 ✅ 已修复
- **问题**: 聊天名称 "W1han" 被错误识别为 "®v QS."
- **原因**: 标题栏识别范围 `title_y_max` 太宽泛，包含窗口控制按钮区域；同时 `_is_garbage()` 过滤不足
- **修复**: 
  - 收紧 Y 范围: `title_y_max=95`（覆盖 y=90 的标题，排除 y≥100 的消息区）
  - 添加 X 范围过滤: `title_x_max_ratio=0.95`
  - 增强 `_is_garbage()` 过滤特殊字符和短噪声
- **验证**: 回归测试 `test_regression_title_y_max_extracts_chat_name` 通过

### 2026-05-04 批量更新 ✅ 已上线
- **结构化 Prompt 重构**
  - System prompt 精简为核心人设 + 工具 + 规则
  - User prompt 改为 `[会话]` / `[对方信息]` / `[历史消息]` / `[未读消息]` 结构化格式
  - 新增 `[已缓存数据]` 段落，注入 SessionMemory 工具缓存
- **SessionMemory 跨 tick 缓存**
  - `wechat_rpa/reply/session_memory.py`
  - web_search 5min / stock_query 1min / get_weather 30min / search_memory 10min
- **新增 browse_url 工具**
  - 支持提取网页正文（含微信公众号文章特殊处理）
  - 正文截断到 3000 字
- **web_search 结果带链接**
  - 提取 360 搜索结果的 URL（解码跳转链接）
  - LLM 可用 browse_url 二次打开感兴趣的结果
- **Hermes 调优**
  - 字数 50 → 300 字
  - 回复条数 0-3 → 0-5 条
- **风格调整**
  - 不用"您"，用"你" casual
  - 口头禅：羡慕你们这些有钱人 / 被你装到了 / 等我有钱了...
- **Bug 修复**
  - debug JSON 中 Hermes 字段残留问题（generate() 开头未重置）
  - 标题栏 OCR 失败时盲目切换导致误点单聊框
  - 聊天列表点击位置偏左，改为正中心 + 更长等待时间

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
python3 run_bot.py
```
- L1-L5 模块化架构（`wechat_rpa/`）
- 双感知管道：SmartPerceptionPipeline（主力，本地预判 + qwen3.6-flash API 兜底） + VisionPipeline（纯本地 OCR 备用回退）
- 环境变量 `USE_MULTIMODAL_OCR=false` 可切换回纯本地模式
- 支持自动登录恢复（`WeChatLoginHandler`）
- 真实场景回归测试覆盖

### Accessibility API 版（已删除）
```bash
# 此版本已删除，功能已合并到模块化架构
```
- 需要辅助功能权限
- 更精确的界面控制

### 历史版本（已删除）
- `core/auto_bot_vision_ocr_v2.py` - 已删除
- `core/auto_bot_vision_ocr_v3.py` - 已删除
- `core/auto_bot_vision_ocr_v4.py` - 已删除（由新架构完全替代）

---

## 关键文件

### 可直接运行版本
| 文件 | 说明 |
|------|------|
| `wechat_rpa/bot/wechat_bot.py` | ⭐ 模块化架构机器人（当前唯一版本） |
| `run_bot.py` | 一键启动脚本（双管道自动选择） |
| `scripts/view_ocr_history.py` | 查看识别历史 |

### 模块化架构（按 `ARCHITECTURE.md` 拆分）
| 文件 | 说明 |
|------|------|
| `wechat_rpa/perception/smart_pipeline.py` | ⭐ L3.5 智能感知管道（主力：本地预判 + qwen3.6-flash API 兜底） |
| `wechat_rpa/perception/vision_pipeline.py` | L3.5 纯本地 OCR 管道（备用回退） |
| `wechat_rpa/session/chat_session.py` | L4 会话与去重 |
| `wechat_rpa/reply/policy.py` | L4 回复决策 |
| `wechat_rpa/reply/generator.py` | L4 回复生成（支持双模型：OpenClaw/Kimi + Hermes） |
| `wechat_rpa/action/message_sender.py` | L4 消息发送 |
| `wechat_rpa/bot/wechat_bot.py` | ⭐ L5 主循环编排 |
| `wechat_rpa/logging/bot_logger.py` | 运行时日志 |
| `wechat_rpa/storage/chat_history.py` | 聊天记录持久化 |
| `wechat_rpa/memory/engine.py` | Memory 引擎 |
| `wechat_rpa/tools/` | Tool Registry & Built-in Tools |

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
