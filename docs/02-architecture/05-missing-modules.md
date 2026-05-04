# 缺失模块清单

> 架构图中引用但尚未实现的模块，按优先级排序。

---

## P0 — 核心流程缺失

### 1. `wechat_rpa/llm/openclaw_client.py` — OpenClaw LLM 客户端 ✅ 已实现
- **引用位置**: `wechat_bot.py` L4 → LLM
- **文件**: `wechat_rpa/llm/openclaw_client.py`（144 行）
- **功能**:
  - 接口与 `qwen_client.py` 兼容（`chat(messages, tools, temperature)` → str）
  - 连接 `http://127.0.0.1:18790`，模型 `kimi-for-coding`
  - 延迟导入 openai 库（未安装时友好报错）
  - 支持 function calling / tool calling
  - 处理 kimi-for-coding 的 `reasoning_content` 占用 max_tokens 配额问题
  - 空内容检测：当 max_tokens 不足时抛出 RuntimeError（绝不返回"收到"）
  - `from_openclaw_config()` 类方法：从 `~/.openclaw/openclaw.json` 自动读取配置
- **状态**: ✅ 已完成

### 2. `wechat_rpa/session/global_store.py` — 全局消息存储 ✅ 已实现
- **引用位置**: `wechat_bot.py` tick → store → merge
- **文件**: `wechat_rpa/session/global_store.py`
- **功能**:
  - 每个聊天一个 `ChatState`（消息列表 + 会话状态）
  - `merge_tick(tick_msgs)` → 未回复消息列表（含新消息 + 历史遗留未回复）
  - `mark_replied(chat_name, target_msg, reply_text)` — 支持 is 匹配 + text+sender 兜底
  - `last_reply_time(chat_name)` / `reply_count(chat_name)` — 统计信息
  - 磁盘持久化（`data/global_state.json`）
  - **去重策略（滑动前缀匹配）**：
    - 在历史消息序列中滑动寻找 tick 的最长前缀匹配位置（允许起点在历史任意位置）
    - tick 全部匹配历史 → 无新消息（用户向上滚动查看旧消息）
    - tick 前缀匹配历史末尾，后缀不匹配 → 后缀为新消息
    - 完全无匹配 → 回退到逐条 `_in_history` 检查
  - **Sender 标准化**：`_normalize_sender()` 统一处理昵称差异
    - `self` → "自己"
    - `other` 且 sender="对方"/空 → 用 `chat_name` 替代（私聊时即为对方昵称）
    - 其余保留原始 sender（群聊中提取到的具体昵称）
  - **模糊去重**：`difflib.SequenceMatcher` + 动态阈值（短消息更严格，0.90→0.80）
  - **图片去重**：2-gram Jaccard，阈值 0.001（极低，容错 qwen 描述不稳定）
- **状态**: ✅ 已完成

---

## P1 — 工具与增强

### 3. `wechat_rpa/tools/tool_registry.py` — 工具注册表 ✅ 已实现
- **引用位置**: `wechat_bot.py` L4 → tools
- **文件**: `wechat_rpa/tools/tool_registry.py`（81 行）
- **功能**:
  - `Tool` 类：name, description, parameters, func
  - `to_openai_schema()` → OpenAI function calling 格式
  - `ToolRegistry`：register / get / has / list_tools / to_openai_schemas
  - 全局单例 `_registry`，通过 `get_registry()` 获取
- **状态**: ✅ 已完成

### 4. `wechat_rpa/tools/builtin_tools.py` — 内置工具 ✅ 已实现
- **引用位置**: `wechat_bot.py` L4 → tools
- **文件**: `wechat_rpa/tools/builtin_tools.py`（163 行）
- **功能**:
  - `_get_current_time()` — 当前时间
  - `_get_weather(city, date)` — wttr.in 天气查询
  - `_web_search(query)` — 网络搜索
  - 导入 `stock_query`（但 `stock_tools.py` 尚未实现，见下方）
  - 注册到全局 ToolRegistry
- **状态**: ⚠️ 基本完成，但 `stock_tools.py` 缺失

### 5. `wechat_rpa/tools/stock_tools.py` — 股票查询工具 ⚠️ 未实现
- **引用位置**: `wechat_rpa/tools/builtin_tools.py` line 12: `from .stock_tools import stock_query`
- **状态**: 🔴 **文件不存在** — builtin_tools.py 引用了该模块但未创建
- **影响**: 导入 builtin_tools.py 时会崩溃（ModuleNotFoundError）
- **建议**: 要么创建 stock_tools.py，要么从 builtin_tools.py 移除该导入

---

## P2 — Action / Memory 模块

### 6. `wechat_rpa/action/chat_list_clicker.py` — 聊天列表点击器 ✅ 已实现
- **引用位置**: 架构图 L5 Action
- **文件**: `wechat_rpa/action/chat_list_clicker.py`（91 行）
- **功能**:
  - 将 OCR/Layouter 识别的 ChatListItem 转换为屏幕点击
  - 坐标计算：`window_rect + item_rect / scale_factor`
  - 点击位置向左偏移 30px 覆盖头像区域
  - 先激活微信窗口确保焦点
- **状态**: ✅ 已完成

### 7. `wechat_rpa/action/login_recovery.py` — 登录恢复 ✅ 已实现
- **引用位置**: 架构图 L5 Action
- **文件**: `wechat_rpa/action/login_recovery.py`（201 行）
- **功能**:
  - 处理微信未登录状态下的自动恢复
  - 检测窗口尺寸异常 → 尝试自动点击登录按钮
  - `LoginRecoveryStatus`: SUCCESS / NEEDS_PHONE_CONFIRM / NEEDS_QRCODE / NO_LOGIN_BUTTON
  - 使用 VisionOCREngine 识别登录按钮
- **状态**: ✅ 已完成

### 8. `wechat_rpa/memory/engine.py` — LLM Wiki 长期记忆 ✅ 已实现
- **引用位置**: 架构图 Memory
- **文件**: `wechat_rpa/memory/engine.py`（441 行）
- **功能**:
  - 基于 LLM Wiki 的长期记忆系统
  - 支持 overrides 配置
  - 用户 wiki 模板：基本信息、偏好、近期动态、说过的话、交互风格
  - `_UPDATE_PROMPT`: 根据对话记录更新 wiki
- **状态**: ✅ 已完成

---

## P3 — 存储模块

### 9. `wechat_rpa/storage/message_store.py` — 消息存储管理 ✅ 已实现
- **引用位置**: 架构图 Storage
- **文件**: `wechat_rpa/storage/message_store.py`（178 行）
- **功能**:
  - `StoredMessage` dataclass：text, sender, sender_type, chat_name, is_at_me, timestamp, message_hash, confidence
  - `MessageStore`：内存缓存 + 磁盘持久化（JSON）
  - 截图管理：`save_screenshot()` → screenshots/
  - 日志管理：`chat_history.txt` 文本日志
  - 去重：基于 message_hash（chat_name + sender + text 的 MD5）
  - 统计：`get_stats()` → total_messages, unique_chats, etc.
- **状态**: ✅ 已完成

---

## 总结

| 优先级 | 模块 | 文件行数 | 状态 |
|--------|------|----------|------|
| P0 | openclaw_client.py | 144 | ✅ 完成 |
| P0 | global_store.py | 243 | ✅ 完成 |
| P1 | tool_registry.py | 81 | ✅ 完成 |
| P1 | builtin_tools.py | 163 | ⚠️ 引用缺失模块 |
| P1 | **stock_tools.py** | 0 | 🔴 **未实现** |
| P2 | chat_list_clicker.py | 91 | ✅ 完成 |
| P2 | login_recovery.py | 201 | ✅ 完成 |
| P2 | memory/engine.py | 441 | ✅ 完成 |
| P3 | message_store.py | 178 | ✅ 完成 |

**唯一未实现模块**: `wechat_rpa/tools/stock_tools.py`（股票查询工具）
- 被 `builtin_tools.py` 导入，会导致 `ModuleNotFoundError`
- 其他所有架构图中引用的模块均已实现
