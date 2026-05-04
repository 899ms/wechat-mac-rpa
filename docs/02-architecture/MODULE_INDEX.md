# 模块索引 (Module Index)

> **本文档描述的是当前已落地的生产架构（Current Production Architecture）。**
>
> AI 开发时的快速导航页。
> 
> 规则：如果你不知道该改哪个文件，先查此表。

---

## 按问题类型索引

### "消息识别错了"
| 现象 | 可能原因 | 修改文件 |
|------|---------|---------|
| 聊天名识别错 | title_y_max / title_x_max_ratio 不准 | `wechat_rpa/layout/profile.py` |
| 输入框内容混入消息 | input_y_min 太松 | `wechat_rpa/layout/profile.py` |
| 时间戳被当成消息 | TIMESTAMP_PATTERNS 不完整 | `wechat_rpa/layout/layout_parser.py` |
| 自己消息被当成对方 | 绿色气泡检测失败 | `wechat_rpa/layout/layout_parser.py` |
| 消息顺序错乱 | 提取时未按 y 排序 | `wechat_rpa/message/extractor.py` |
| 昵称识别错 | nickname 区域边界不对 | `wechat_rpa/layout/profile.py` |

### "回复时机错了"
| 现象 | 可能原因 | 修改文件 |
|------|---------|---------|
| 自己发的话又回复 | 去重/回声检测失效 | `wechat_rpa/session/chat_session.py` |
| 对同一句话反复回复 | `filter_new()` 去重不严格 | `wechat_rpa/session/chat_session.py` |
| 群聊没@也回复 | `@检测` 或 `群聊判断` 错误 | `wechat_rpa/reply/policy.py` |
| 回复太频繁 | cooldown 时间太短 | `wechat_rpa/session/chat_session.py` |

### "发送内容错了"
| 现象 | 可能原因 | 修改文件 |
|------|---------|---------|
| 回复内容太长/太啰嗦 | 系统提示词 | `wechat_rpa/reply/generator.py` |
| 回复不相关 | LLM prompt 或上下文 | `wechat_rpa/reply/generator.py` |

### "发送动作异常"
| 现象 | 可能原因 | 修改文件 |
|------|---------|---------|
| 发出去是乱码 | 用了 keystroke 输入中文 | `wechat_rpa/action/message_sender.py` |
| 没发出去 | AppleScript 失败 | `wechat_rpa/action/message_sender.py` |
| 切换聊天失败 | 坐标点击未命中或聊天列表未识别 | `wechat_rpa/action/ui_interactor.py` / `wechat_rpa/layout/layout_parser.py` |
| 截图失败 | 找不到微信窗口 | `wechat_rpa/capture/window_capture.py` |

### "排查问题找不到信息"
| 现象 | 可能原因 | 修改文件 |
|------|---------|---------|
| 不知道 Bot 为什么没回复 | execution.jsonl 缺少 decision 日志 | `wechat_rpa/logging/bot_logger.py` |
| 历史记录丢失/找不到 | ChatHistory 路径或写入逻辑错误 | `wechat_rpa/storage/chat_history.py` |
| 单文件过大加载慢 | 未按 chat_name 分片 jsonl | `wechat_rpa/storage/chat_history.py` |

---

## 按文件索引

### `wechat_rpa/models/base.py`
- **定位**: L1 领域模型
- **改什么**: 基础数据结构变更
- **不改什么**: 业务逻辑

### `wechat_rpa/capture/window_capture.py`
- **定位**: L2 截图
- **改什么**: 窗口查找逻辑、截图方式、Retina 适配
- **不改什么**: OCR、消息解析

### `wechat_rpa/ocr/vision_ocr.py`
- **定位**: L2 OCR
- **改什么**: 改用其他 OCR 引擎（如 EasyOCR）、坐标转换
- **不改什么**: 过滤、布局解析

### `wechat_rpa/layout/profile.py`
- **定位**: L2 配置
- **改什么**: 所有边界值、颜色阈值
- **不改什么**: 解析逻辑本身

### `wechat_rpa/layout/layout_parser.py`
- **定位**: L3 布局分组
- **改什么**: 区域分组算法、时间戳检测、气泡检测
- **不改什么**: 消息去重、发送逻辑

### `wechat_rpa/message/extractor.py`
- **定位**: L3 消息提取
- **改什么**: 消息合并规则、昵称匹配、sender_type 判定
- **不改什么**: OCR、截图

### `wechat_rpa/perception/smart_pipeline.py`
- **定位**: L3.5 智能感知管道（主力）
- **改什么**: 本地预判与 API 兜底的切换逻辑、像素差异阈值、多模态 API 调用
- **不改什么**: 去重策略、回复生成

### `wechat_rpa/perception/vision_pipeline.py`
- **定位**: L3.5 纯本地 OCR 管道（备用回退）
- **改什么**: 聚合视觉链路、错误处理、聊天切换预留接口
- **不改什么**: 去重策略、回复生成

### `wechat_rpa/session/chat_session.py`
- **定位**: L4 会话/去重
- **改什么**: 去重算法、冷却策略、回声检测
- **不改什么**: 回复生成

### `wechat_rpa/reply/policy.py`
- **定位**: L4 决策
- **改什么**: 回复触发条件、@检测、私聊/群聊区分
- **不改什么**: 发送执行

### `wechat_rpa/reply/generator.py`
- **定位**: L4 生成
- **改什么**: Prompt 工程、LLM 调用
- **不改什么**: 去重逻辑
- **注意**: 兜底回复已废弃（返回空列表），不再生成固定话术

### `wechat_rpa/action/message_sender.py`
- **定位**: L4 执行
- **改什么**: 发送方式、剪贴板处理、快捷键
- **不改什么**: 回复内容决策

### `wechat_rpa/action/ui_interactor.py`
- **定位**: L4 坐标/UI 操作
- **改什么**: 聊天列表点击、输入框聚焦、坐标点击逻辑
- **不改什么**: 回复内容决策
- **依赖**: 由 `VisionPipeline` / `LayoutParser` 提供 `ChatListItem` 坐标

### `wechat_rpa/bot/wechat_bot.py`
- **定位**: L5 编排
- **改什么**: 主循环流程、错误处理、多会话管理
- **原则**: 保持薄（thin），只负责调用各层，不包业务逻辑

### `wechat_rpa/logging/bot_logger.py`
- **定位**: L4 可观测性
- **改什么**: 日志级别、execution.jsonl 事件类型、埋点位置
- **不改什么**: 业务决策逻辑
- **排查必读: [../03-guides/LOGGING_DESIGN.md](../03-guides/LOGGING_DESIGN.md)`

### `wechat_rpa/storage/chat_history.py`
- **定位**: L4 持久化
- **改什么**: 分片策略、查询接口、HistoryRecord 字段、旧版迁移逻辑
- **不改什么**: 去重算法（那是 Session 的事）
- **排查必读: [../03-guides/LOGGING_DESIGN.md](../03-guides/LOGGING_DESIGN.md)`

---

## 依赖图

```
models/base.py
    ↑
    ├── capture/window_capture.py
    ├── ocr/vision_ocr.py
    ├── layout/profile.py
    │       ↑
    │   layout/layout_parser.py
    │
    ├── message/extractor.py
    │       ↑
    │   perception/vision_pipeline.py  ← 纯本地 OCR 管道
    │       ↑
    │   perception/smart_pipeline.py  ← 主力：本地预判 + API 兜底
    │       ↑
    │   session/chat_session.py
    │   reply/policy.py
    │   reply/generator.py
    │   action/message_sender.py
    │   action/ui_interactor.py
    │       ↑
    │   bot/wechat_bot.py
    │
    ├── logging/bot_logger.py
    └── storage/chat_history.py
```

**注意**: 箭头方向表示 "被依赖"。没有循环依赖。

**新增依赖规则**: `logging` 和 `storage/chat_history` 可被 Bot (L5) 直接依赖，但不可被 L1-L3 依赖。
