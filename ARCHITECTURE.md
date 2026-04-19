# 微信 Mac RPA 架构设计文档

> ⚠️ **重要提示：本文档描述的是目标重构架构（Target Architecture），而非当前实际代码结构。**
> 
> 当前实际代码位于 `wechat_rpa/` 目录下，但结构与本文档存在差异（例如：当前使用 `wechat_rpa/parser/wechat_parser.py` 统一处理解析，而非本文档中的 `layout/` + `message/` 拆分；当前 `action/reply_generator.py` 同时包含策略与生成逻辑，而非本文档中的 `reply/policy.py` + `reply/generator.py` 拆分）。
> 
> **文档分类**：`ARCHITECTURE.md`、`API_SURFACE.md`、`MODULE_INDEX.md` 属于**重构目标文档**。其他文档（如 `README.md`、`PROJECT_STATUS.md`、`LESSONS_LEARNED.md`）主要描述**当前实现**。
> 
> 目标：让任何 AI Agent 在 5 分钟内理解系统结构，并能独立修改任一模块。

---

## 一、架构总览

### 1.1 核心原则

1. **单一职责**：每个文件只做一件事
2. **依赖单向**：上层可调用下层，下层不可反向依赖
3. **配置与代码分离**：所有布局相关的边界常量提取到 `LayoutProfile`，会话/策略参数提取到对应 L4 模块
4. **测试即文档**：每个模块有独立单元测试

### 1.2 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5: Application                                       │
│  wechat_rpa/bot/wechat_bot.py                               │
│  主循环编排：perceive → session → policy → generate → action│
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│  Layer 4:    │    │  Layer 4:       │    │  Layer 4:    │
│  Session     │    │  Reply          │    │  Action      │
│  会话/去重   │    │  回复决策/生成  │    │  执行发送    │
└──────────────┘    └─────────────────┘    └──────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3.5: Vision Pipeline                                 │
│  wechat_rpa/perception/vision_pipeline.py                   │
│  感知管道：capture → ocr → layout → extract                 │
│  对 Bot 层完全隐藏视觉实现细节                              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│  Layer 3:    │    │  Layer 3:       │    │  Layer 2:    │
│  Message     │    │  Layout         │    │  Capture     │
│  消息模型/   │    │  布局解析器     │    │  窗口截图    │
│  提取器      │    │                 │    │              │
└──────────────┘    └─────────────────┘    └──────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│  Layer 2:    │    │  Layer 2:       │    │              │
│  OCR         │    │  LayoutProfile  │    │              │
│  文字识别    │    │  布局配置       │    │              │
└──────────────┘    └─────────────────┘    └──────────────┘
        │                     │
        ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Domain Models                                     │
│  基础数据类型：Point, Rect, OCRTextElement,                 │
│  ChatMessage, SentMessage, ActionResult, PerceptionResult   │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 依赖规则

- **Domain (L1)** 不依赖任何其他层
- **Capture / OCR / LayoutProfile (L2)** 只依赖 L1
- **Message / Layout (L3)** 只依赖 L1-L2
- **VisionPipeline (L3.5)** 可依赖 L1-L3，但**对 L4-L5 隐藏内部细节**
- **Session / Reply / Action (L4)** 可依赖 L1 和 L3.5 的输出（`ChatMessage`, `PerceptionResult`），**不可直接依赖 L2-L3 的内部实现**
- **Bot (L5)** 只依赖 L1、L3.5、L4。**Bot 层禁止直接 import OCR/Layout/Capture**

**禁止**：
- 下层模块 `import` 上层模块
- Bot 层直接操作 `OCRTextElement`、`UILayout`、`CaptureResult`
- Session 层暴露视觉实现细节给 Bot 层

---

## 二、各模块详细设计

### 2.1 Domain Models (L1)

**文件**: `wechat_rpa/models/base.py`

**职责**: 定义整个系统的基础数据结构。无业务逻辑，纯数据容器。

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

@dataclass(frozen=True)
class Point:
    x: int
    y: int

@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

@dataclass
class OCRTextElement:
    """OCR 原始输出元素"""
    text: str
    bbox: Rect           # 外接矩形
    center: Point        # 中心点，用于位置判断
    confidence: float

class SenderType(Enum):
    SELF = "self"
    OTHER = "other"
    SYSTEM = "system"
    UNKNOWN = "unknown"

@dataclass
class ChatMessage:
    """领域模型：一条聊天消息"""
    text: str
    sender: str
    sender_type: SenderType
    chat_name: str
    is_at_me: bool = False
    timestamp: Optional[str] = None
    source_elements: Optional[List[OCRTextElement]] = None  # 溯源：仅供 L3 Extractor 构造消息和 L4 Session debug 使用，Bot 层禁止读取

@dataclass
class SentMessage:
    """记录由 Bot 自己发送的消息"""
    text: str
    sent_at: float

@dataclass
class ActionResult:
    success: bool
    sent_text: Optional[str] = None
    error: Optional[str] = None

@dataclass
class ChatListItem:
    """左侧聊天列表项，属于 Domain Model，被 Layout 和 UIInteractor 共用"""
    nickname: str
    last_message_preview: str
    unread_count: str
    timestamp: str
    rect: Rect  # 列表项在屏幕上的位置，供 UIInteractor 点击使用

@dataclass
class PerceptionResult:
    """VisionPipeline 的输出，对 Bot 层隐藏所有视觉实现细节"""
    chat_name: str
    messages: List[ChatMessage]
    chat_list_items: List[ChatListItem]
    screenshot_path: str
```

**设计要点**:
- `OCRTextElement` 是 OCR 层和 Layout 层的通用接口
- `ChatMessage.source_elements` 保留溯源能力，方便 debug
- `SentMessage` 记录 Bot 自己发送的消息，用于回声检测

---

### 2.2 Capture (L2)

**文件**: `wechat_rpa/capture/window_capture.py`

**职责**: 找到微信窗口并截图。输出原始图片。

**接口**:

```python
class WindowCapture:
    def __init__(self, output_path: str = None,
                 min_effective_width: int = 800,
                 min_effective_height: int = 600):
        pass

    def capture(self) -> CaptureResult:
        """
        查找并截图微信主窗口。

        如果找到的最大窗口尺寸过小（< min_effective_width × min_effective_height），
        会先尝试 `osascript -e 'tell application "WeChat" to activate'` 激活微信，
        等待 2 秒后重试。重试后仍无效则抛出 `WeChatNotReadyError`。

        Returns:
            CaptureResult: 包含图片路径和窗口几何信息

        Raises:
            WindowNotFoundError: 未找到任何微信窗口
            WeChatNotReadyError: 窗口尺寸异常，可能需要扫码登录
        """
        pass

@dataclass
class CaptureResult:
    image_path: str
    window_rect: Rect
    scale_factor: float  # Retina 屏幕为 2.0，普通屏幕为 1.0
```

**实现细节**:
- 使用 `Quartz.CGWindowListCopyWindowInfo` 枚举窗口
- 过滤条件：`owner in ['WeChat', '微信']` 且 `width > 200, height > 200`
- 在多个窗口中选择**面积最大**的窗口
- 如果最大窗口仍小于 `min_effective_width × min_effective_height`（默认 800×600），自动激活微信并重试
- 重试无效时抛出 `WeChatNotReadyError`，提示可能需要扫码登录
- 使用 `screencapture -R` 命令截图
- 自动处理 Retina 屏幕缩放

**测试策略**:
- Mock Quartz 窗口列表，验证能正确识别主窗口
- 验证截图文件生成且尺寸与窗口声明一致

---

### 2.3 OCR (L2)

**文件**: `wechat_rpa/ocr/vision_ocr.py`

**职责**: 从图片中提取文本元素。不做任何过滤或解释。

**接口**:

```python
class VisionOCREngine:
    def recognize(self, image_path: str) -> List[OCRTextElement]:
        """
        识别图片中的所有文本。
        
        Args:
            image_path: 图片文件路径
            
        Returns:
            OCRTextElement 列表，按 y 坐标从上到下排序
        """
        pass
```

**实现细节**:
- 使用 macOS Vision 框架 (`VNRecognizeTextRequest`)
- 将 Vision 的归一化坐标转换为像素坐标
- 输出按 `center.y` 升序排列

**约束**:
- 不过滤时间戳
- 不判断 sender_type
- 不做任何业务假设

**测试策略**:
- 用固定测试图片，验证输出元素数量和文本内容
- 验证坐标转换正确

---

### 2.4 LayoutProfile (L2)

**文件**: `wechat_rpa/layout/profile.py`

**职责**: 把写死的布局常量提取为配置对象。

**接口**:

```python
@dataclass
class LayoutProfile:
    """
    针对特定微信版本 + 分辨率的布局配置。
    当微信更新或窗口缩放异常时，优先调整此配置。
    """
    name: str
    window_width: int           # 适配窗口宽度
    window_height: int          # 适配窗口高度
    
    # 区域边界（像素）
    left_boundary: int          # 聊天列表右边界
    chat_list_x_max: int        # 聊天列表最大 x
    title_y_max: int            # 标题栏底部
    title_x_max_ratio: float    # 标题栏右侧比例上限
    input_y_min: int            # 输入框顶部
    
    # 颜色检测
    self_green: Tuple[int, int, int]
    self_green_tolerance: int
    min_bubble_pixels: int      # 气泡最小像素数
    message_cluster_threshold: int = 80  # 消息按 y 聚类的阈值（像素）
    
    # 昵称识别区域（相对坐标 0.0-1.0）
    nickname_x_min_ratio: float
    nickname_x_max_ratio: float
    nickname_y_offset_min: int
    nickname_y_offset_max: int

# 预配置实例
PROFILE_WECHAT_MAC_1760X1280 = LayoutProfile(
    name="wechat_mac_4.1.8_1760x1280",
    window_width=1760,
    window_height=1280,
    left_boundary=420,
    chat_list_x_max=320,
    title_y_max=50,
    title_x_max_ratio=0.70,
    input_y_min=1160,
    self_green=(176, 240, 167),
    self_green_tolerance=35,
    min_bubble_pixels=1000,
    message_cluster_threshold=80,
    nickname_x_min_ratio=0.30,
    nickname_x_max_ratio=0.55,
    nickname_y_offset_min=15,
    nickname_y_offset_max=50,
)
```

**设计要点**:
- 所有边界值集中在一处
- 支持多 profile，未来可自动检测窗口尺寸匹配对应 profile
- 修改布局阈值时，不需要改动业务代码

---

### 2.5 Layout Parser (L3)

**文件**: `wechat_rpa/layout/layout_parser.py`

**职责**: 把 OCR 元素按 UI 区域分组。输出 `UILayout`。

**关键设计**: **只做分组，不做过滤**。不判断"这是不是消息"。

**接口**:

```python
class LayoutParser:
    def __init__(self, profile: LayoutProfile):
        self.profile = profile
    
    def parse(self, elements: List[OCRTextElement], image_path: str) -> UILayout:
        """
        将 OCR 元素分组为 UI 区域。
        
        Returns:
            UILayout: 包含各区域元素的完整布局描述
        """
        pass

@dataclass
class UILayout:
    """UI 布局分组结果"""
    chat_name: str
    
    # 左侧聊天列表
    chat_list_items: List[ChatListItem]
    
    # 右侧区域分组
    title_elements: List[OCRTextElement]
    input_elements: List[OCRTextElement]
    timestamp_elements: List[OCRTextElement]
    self_bubbles: List[Rect]       # 绿色气泡区域
    message_candidates: List[OCRTextElement]  # 在消息区的所有元素
```

**分组逻辑**:

1. **左右分割**: `x < left_boundary` 为左侧（聊天列表），`x >= left_boundary` 为右侧（聊天内容区）。`chat_list_x_max` 是左侧列表的有效宽度上限（用于过滤聊天列表内的噪点），分割时主边界仍用 `left_boundary`
2. **标题栏**: 右侧中 `y < title_y_max` 且 `x < width * title_x_max_ratio` 的元素（width 从 image_path 对应图片的宽度获取）
3. **输入框**: 右侧中 `y >= input_y_min` 的元素
4. **时间戳**: 匹配预定义正则模式 `TIMESTAMP_PATTERNS` 且位于消息区中央的元素
5. **绿色气泡**: 通过颜色检测（`self_green`）识别，过滤小噪点
6. **消息候选区**: 右侧中排除上述分组后的剩余元素

**时间戳模式**:

```python
TIMESTAMP_PATTERNS = [
    r"^\d{1,2}:\d{2}$",                     # 12:34
    r"^昨天 \d{1,2}:\d{2}$",                 # 昨天 12:34
    r"^星期[一二三四五六日] \d{1,2}:\d{2}$",  # 星期一 12:34
    r"^\d{4}/\d{2}/\d{2}$",                  # 2024/01/15
]
```

**约束**:
- 不调用 LLM
- 不判断 sender_type
- 不做消息合并

**测试策略**:
- 用测试图片验证各区域元素数量
- 验证 `chat_name` 提取正确
- 验证绿色气泡数量和位置正确

---

### 2.6 Message Extractor (L3)

**文件**: `wechat_rpa/message/extractor.py`

**职责**: 从 `UILayout` 中提取结构化消息列表 `List[ChatMessage]`。

**接口**:

```python
class MessageExtractor:
    def __init__(self, profile: LayoutProfile):
        self.profile = profile
    
    def extract(self, layout: UILayout) -> List[ChatMessage]:
        """
        从 UI 布局中提取消息。
        
        逻辑：
        1. 先处理 self_bubbles 内的文本 → SELF 消息
        2. 再处理其他候选文本 → OTHER 消息
        3. 按 y 坐标排序
        
        Returns:
            ChatMessage 列表，按时间顺序排列
        """
        pass
```

**提取规则**:

**自己消息**:
- 文本中心点落在 `self_bubbles` 内的元素
- 同一气泡内的多个文本按 y 排序后合并
- `sender_type = SELF`

**对方消息**:
- 不在任何 self_bubble 内的 `message_candidates`
- 按 y 坐标聚类（间距 < `profile.message_cluster_threshold` 为一组）
- 检查聚类顶部是否有昵称（在 `nickname_x_min_ratio` ~ `nickname_x_max_ratio` 对应区域内）
- `sender_type = OTHER`

**系统消息**:
- 已提前在 Layout 阶段归入 `timestamp_elements`
- 这里不处理

**测试策略**:
- 验证消息数量与气泡数量匹配
- 验证 sender_type 识别正确率
- 验证消息按 y 坐标正确排序

---

### 2.7 Vision Pipeline (L3.5)

**文件**: `wechat_rpa/perception/vision_pipeline.py`

**职责**: 将 Capture → OCR → Layout → Extract 的完整视觉链路封装为单一接口。对 Bot 层完全隐藏视觉实现细节。

**接口**:

```python
class VisionPipeline:
    def __init__(self, profile: LayoutProfile):
        self.capture = WindowCapture()
        self.ocr = VisionOCREngine()
        self.layout = LayoutParser(profile)
        self.extractor = MessageExtractor(profile)
    
    def perceive(self) -> Optional[PerceptionResult]:
        """
        执行完整视觉链路：截图 → OCR → 布局分组 → 消息提取。
        
        Returns:
            PerceptionResult: 包含结构化消息列表、聊天名、截图路径
            None: 当 Capture 失败（如未找到窗口）时返回 None，由 Bot 层跳过本轮
        """
        pass
    

```

**设计要点**:
- Bot 层禁止直接操作 `OCRTextElement`、`UILayout`、`CaptureResult`
- `VisionPipeline` 是 Bot 层与视觉系统之间的唯一边界

---

### 2.8 Chat Session (L4)

**文件**: `wechat_rpa/session/chat_session.py`

**职责**: 会话状态管理 + 去重核心。**这是防止循环发送的关键层。**

**接口**:

```python
class ChatSession:
    def __init__(
        self,
        chat_id: str,
        chat_name: str,
        echo_time_window: float = 10.0,
        echo_history_limit: int = 5,
    ):
        self.chat_id = chat_id
        self.chat_name = chat_name
        self.echo_time_window = echo_time_window
        self.echo_history_limit = echo_history_limit
        
        # 已见过消息的去重缓存：key = (chat_name, sender, text_hash)
        self.seen_messages: Set[Tuple[str, str, str]] = set()
        
        # 已见过的消息窗口指纹（用于检测滚动导致的重复视图），最多保留最近 100 个
        from collections import deque
        self.seen_window_hashes: deque[str] = deque(maxlen=100)
        
        # 自己发送的消息记录（用于回声检测）
        self.sent_messages: List[SentMessage] = []
        
        self.last_reply_time: Optional[float] = None
        self.reply_count: int = 0
    
    def filter_new(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        """
        从当前识别的消息列表中过滤出真正的新消息。
        
        检查顺序（重要）：
        1. 窗口指纹检测（如果整体消息列表近期已出现过，认为是滚动重复）
        2. 逐条回声检测（是否是自己刚发的消息）
        3. 上下文去重（结合上一条消息是否也匹配历史，判断是否为重复）
        """
        pass
    
    def record_sent(self, text: str) -> None:
        """记录 Bot 自己发送的消息。"""
        pass
    
    def is_in_cooldown(self, seconds: float = 30.0) -> bool:
        """检查是否在冷却期内"""
        pass
    
    # 注意：回复决策统一由 ReplyPolicy 负责，Session 只提供状态查询

# 去重键直接使用 Tuple[str, str, str] = (chat_name, sender, text_hash)
# 若未来去重逻辑需要更多字段，可重新引入 MessageIdentity
```

**去重算法**（完整类内实现）：

```python
import time
from hashlib import md5

class ChatSession:
    # ... __init__ 如上 ...

    def filter_new(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        if not messages:
            return []
        
        # 1. 窗口指纹检测：如果整个消息列表近期已出现过，认为是滚动重复
        window_hash = self._hash_messages(messages)
        if window_hash in self.seen_window_hashes:
            return []
        
        new_messages = []
        for i, msg in enumerate(messages):
            # 2. 回声检测：是否是自己刚发的
            if any(self._is_echo(msg.text, sent) for sent in reversed(self.sent_messages[-self.echo_history_limit:])):
                continue
            
            # 3. 上下文去重：如果该消息及其上一条都与历史匹配，则认为是重复视图
            if self._is_seen_with_context(msg, messages, i):
                continue
            
            new_messages.append(msg)
        
        # 将本轮所有消息记录到 seen_messages，供下一轮上下文去重使用
        for msg in messages:
            key = (msg.chat_name, msg.sender, md5(msg.text.encode()).hexdigest())
            self.seen_messages.add(key)
        
        self.seen_window_hashes.append(window_hash)
        return new_messages

    def _is_echo(self, msg_text: str, sent: SentMessage) -> bool:
        """判断 msg 是否是 sent 的"回声"。条件：时间窗口内 + 文本包含关系。"""
        time_match = (time.time() - sent.sent_at) < self.echo_time_window
        text_match = sent.text in msg_text or msg_text in sent.text
        return time_match and text_match

    def _is_seen_with_context(self, msg: ChatMessage, messages: List[ChatMessage], index: int) -> bool:
        """
        结合上下文判断 msg 是否是重复消息。
        如果 msg 本身已在 seen_messages 中，且上一条消息也匹配历史，则大概率是滚动导致的重复视图。
        """
        key = (msg.chat_name, msg.sender, md5(msg.text.encode()).hexdigest())
        if key not in self.seen_messages:
            return False
        
        # 上下文检查：上一条消息是否也在 seen_messages 中
        if index > 0:
            prev = messages[index - 1]
            prev_key = (prev.chat_name, prev.sender, md5(prev.text.encode()).hexdigest())
            if prev_key in self.seen_messages:
                return True
        
        return False

    def _hash_messages(self, messages: List[ChatMessage]) -> str:
        """计算消息列表的上下文指纹。"""
        content = "|".join(
            f"{m.chat_name}:{m.sender}:{md5(m.text.encode()).hexdigest()}"
            for m in messages
        )
        return md5(content.encode()).hexdigest()
```

**设计要点**:
- 去重核心不在 Storage，而在 Session
- `sent_messages` 明确记录"这是我发的"
- 回声检测以 **时间窗口**（10 秒内）和 **文本包含** 为主要条件
- 引入 **窗口指纹** 和 **上下文去重** 解决聊天滚动导致的 Y 坐标不可靠问题

---

### 2.9 Reply Policy & Generator (L4)

**文件**: 
- `wechat_rpa/reply/policy.py`
- `wechat_rpa/reply/generator.py`

**职责**:
- `policy`: 决定是否回复
- `generator`: 生成回复内容

**接口**:

```python
class ReplyPolicy:
    def should_reply(self, msg: ChatMessage, session: ChatSession) -> bool:
        """
        决策逻辑：
        1. 自己消息 → False
        2. 系统消息 → False
        3. 冷却期内同一聊天 → False
        4. 群聊且未@我 → False
        5. 其他 → True
        """
        pass

class ReplyGenerator:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client or KimiClient()
    
    def generate(self, msg: ChatMessage, session: ChatSession) -> str:
        """
        调用 LLM 生成回复。
        
        系统提示词固定：
        - 友好自然
        - 简洁（≤50字）
        - 群聊@时直接回答
        """
        pass
```

**约束**:
- `generator` 只做内容生成，不做发送决策
- 生成失败时返回兜底文案 "收到"

---

### 2.10 Action Layer (L4)

**文件**: `wechat_rpa/action/message_sender.py`、`wechat_rpa/action/ui_interactor.py`

**职责**: 执行所有与微信窗口的交互操作，分为两类：
- `MessageSender`：内容输入（文本、图片、文件）
- `UIInteractor`：坐标/UI 操作（点击聊天项、切换聊天）

#### MessageSender

```python
class MessageSender:
    def send(self, text: str) -> ActionResult: ...
    def send_image(self, image_path: str) -> ActionResult: ...
    def send_file(self, file_path: str) -> ActionResult: ...
```

**当前实现（文本）**：基于 AppleScript 的全局键盘事件（`Command+V` 粘贴 + `Return` 发送）。只要微信窗口处于前台激活状态且光标在输入框中，就不需要知道输入框的像素坐标。

```python
class WeChatMessageSender(MessageSender):
    def send(self, text: str) -> ActionResult:
        try:
            # 确保微信窗口在前台，防止消息发到其他应用
            subprocess.run(['osascript', '-e', 'tell application "WeChat" to activate'], timeout=3, capture_output=True)
            time.sleep(0.1)
            
            subprocess.run(['pbcopy'], input=text.encode('utf-8'), timeout=2)
            time.sleep(0.15)
            script = '''
                tell application "System Events"
                    tell process "WeChat"
                        keystroke "v" using command down
                        delay 0.15
                        keystroke return
                    end tell
                end tell
            '''
            subprocess.run(['osascript', '-e', script], timeout=5, capture_output=True)
            return ActionResult(success=True, sent_text=text)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
    
    def send_image(self, image_path: str) -> ActionResult:
        """预留：将图片复制到剪贴板后 Command+V 粘贴发送。"""
        pass
    
    def send_file(self, file_path: str) -> ActionResult:
        """预留：拖拽文件到输入框或复制到剪贴板后粘贴发送。"""
        pass
```

**禁忌**:
- 不能用 `keystroke "a" using command down` 这类全选操作（中文 IME 会产生产拼音碎片）
- 不能用 `typewrite` 逐字符输入（同样受 IME 影响）

#### UIInteractor

```python
class UIInteractor:
    def click_chat_item(self, item: ChatListItem) -> bool: ...
    def click_input_box(self) -> bool: ...
```

**职责**：基于坐标进行鼠标点击操作，用于切换聊天或聚焦输入框。

**为什么当前发送文本不需要坐标，但还需要 `UIInteractor`？**
- 当前发送文本只需要键盘（光标已在输入框）
- 切换聊天、发送图片/文件后的聚焦、未来拖拽文件等场景**必须依赖坐标点击**
- `UIInteractor` 由 `VisionPipeline` 输出的 `ChatListItem` / `Rect` 驱动，Bot 层不直接接触坐标

#### WeChatLoginHandler

**文件**: `wechat_rpa/action/login_recovery.py`

**职责**: 当 `WindowCapture` 检测到微信窗口尺寸异常（未登录/浮窗）时，尝试自动恢复。

**接口**:

```python
class LoginRecoveryStatus(Enum):
    SUCCESS = "success"
    NEEDS_PHONE_CONFIRM = "needs_phone_confirm"
    NEEDS_QRCODE = "needs_qrcode"
    NO_LOGIN_BUTTON = "no_login_button"

class WeChatLoginHandler:
    def __init__(self, capture_output: str = "/tmp/wechat_login_capture.png",
                 login_keywords: List[str] = None,
                 min_effective_width: int = 800,
                 min_effective_height: int = 600): ...
    def handle(self) -> LoginRecoveryResult: ...
```

**恢复流程**:
1. 查找微信窗口并截图
2. OCR 识别：
   - 如果已出现 **"需在手机上完成登录"**，直接返回 `NEEDS_PHONE_CONFIRM`
   - 如果检测到 **"登录" / "进入微信"** 等关键词，计算按钮坐标并尝试点击
3. 点击后等待 8 秒（给手机确认留足时间）
4. 再次检查窗口尺寸：
   - 窗口 ≥ 800×600 → `SUCCESS`
   - 窗口仍小但出现手机确认提示 → `NEEDS_PHONE_CONFIRM`
   - 窗口仍小且无提示 → `NEEDS_QRCODE`（提示用户手动点击或在手机上确认）

**点击实现**: 使用 AppleScript / Quartz / cliclick 做 best-effort 尝试，不保证 100% 成功（受 macOS 辅助功能和微信安全机制影响）。

---

### 2.11 Bot Orchestrator (L5)

**文件**: `wechat_rpa/bot/wechat_bot.py`

**职责**: 主循环编排，把各层串起来。

**接口**:

```python
class WeChatBot:
    def __init__(self, profile: LayoutProfile, on_message: Optional[Callable] = None):
        # Bot 层只依赖 VisionPipeline，禁止直接持有 Capture/OCR/Layout/Extractor
        self.perception = VisionPipeline(profile)
        self.sessions: Dict[str, ChatSession] = {}
        self.policy = ReplyPolicy()
        self.generator = ReplyGenerator()
        self.sender = WeChatMessageSender()
        self.on_message = on_message  # 预留：外部系统集成回调
        self.running = False
    
    def tick(self) -> None:
        """执行一轮：感知 → 去重 → 决策 → 回复"""
        pass
    
    def run_auto(self, interval: float = 5.0) -> None:
        while self.running:
            self.tick()
            time.sleep(interval)
    
    def _get_session(self, chat_name: str) -> ChatSession:
        """获取或创建指定聊天的会话对象。"""
        pass
    
    def send_to_chat(self, chat_name: str, text: str) -> ActionResult:
        """预留：外部系统调用此接口主动发消息到指定聊天。"""
        pass
```

**主循环伪代码**:

```python
def tick(self) -> None:
    # 所有视觉细节对 Bot 隐藏，统一走 Pipeline
    result = self.perception.perceive()
    if result is None:
        # 未找到窗口或截图失败，跳过本轮
        return
    
    messages = result.messages
    chat_name = result.chat_name
    
    session = self._get_session(chat_name)
    new_messages = session.filter_new(messages)
    
    if not new_messages:
        return
    
    # 推送新消息给外部系统（如 OpenClaw）
    for msg in new_messages:
        if self.on_message:
            self.on_message(msg, session)
    
    latest = new_messages[-1]
    should_send = self.policy.should_reply(latest, session)
    
    if should_send:
        reply = self.generator.generate(latest, session)
        if reply:
            action_result = self.sender.send(reply)
            if action_result.success:
                session.record_sent(reply)
```

**运行一次的数据流**:

```
[Capture]        screenshot.png
    ↓
[OCR]            List<OCRTextElement>
    ↓
[LayoutParser]   UILayout
    ↓
[Extractor]      List<ChatMessage>
    ↓
[Session]        过滤为 new_messages
    ↓
[ReplyPolicy]    should_reply ?
    ↓
[Generator]      reply_text
    ↓
[Sender]         ActionResult
    ↓
[Session]        record_sent(reply)
```

---

### 2.12 Logging (L4)

**文件**: `wechat_rpa/logging/bot_logger.py`

**职责**: 记录 Bot 运行期事件，输出到 `execution.jsonl`。

**接口**:

```python
class BotLogger:
    def __init__(self, logs_dir: str = None, max_bytes: int = 5*1024*1024, backup_count: int = 3) -> None: ...
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str, exc_info: bool = False) -> None: ...
    def critical(self, msg: str) -> None: ...
    def log_tick_start(self, tick_id: int, interval: float) -> None: ...
    def log_capture(self, tick_id: int, success: bool, window_info: dict = None, error: str = None) -> None: ...
    def log_ocr(self, tick_id: int, element_count: int, duration_ms: float, sample_texts: List[str]) -> None: ...
    def log_layout(self, tick_id: int, chat_name: str, title_elem_count: int, input_elem_count: int, timestamp_elem_count: int, self_bubble_count: int, message_candidate_count: int) -> None: ...
    def log_messages(self, tick_id: int, total_messages: int, new_messages: int, message_details: List[dict]) -> None: ...
    def log_decision(self, tick_id: int, should_reply: bool, reason: str, latest_text: str, reply_text: str = None, extra: dict = None) -> None: ...
    def log_send(self, tick_id: int, success: bool, text: str, error: str = None) -> None: ...
    def log_exception(self, tick_id: int, phase: str, exc: Exception) -> None: ...
    def log_stats(self, tick_id: int, stats: dict) -> None: ...
```

**设计要点**:
- 采用结构化 JSONL 格式，便于后续查询和分析
- 日志目录默认在 `logs/`，支持自动轮转

---

### 2.13 Storage (L4)

**文件**: `wechat_rpa/storage/chat_history.py`

**职责**: 持久化聊天历史记录，按 `chat_name` 分片存储。

**接口**:

```python
@dataclass
class HistoryRecord:
    text: str
    sender: str
    sender_type: str
    chat_name: str
    is_at_me: bool = False
    timestamp: str = ""
    message_hash: str = ""
    confidence: float = 0.0
    bubble_y: int = 0          # 用于位置关联和回声检测
    source: str = "ocr"
    tick_id: int = 0
    screenshot_path: str = ""

class ChatHistory:
    def __init__(self, storage_dir: str = None) -> None: ...
    def append_messages(self, chat_name: str, messages: List[ChatMessage], tick_id: int = 0, screenshot_path: str = "") -> List[HistoryRecord]: ...
    def get_messages(self, chat_name: Optional[str] = None, since: datetime = None, until: datetime = None, limit: int = 500) -> List[HistoryRecord]: ...
    def get_recent_chats(self, hours: float = 24.0, limit: int = 100) -> Dict[str, List[HistoryRecord]]: ...
    def get_last_message(self, chat_name: str) -> Optional[HistoryRecord]: ...
    def get_stats(self) -> dict: ...
    def export_chat(self, chat_name: str, output_path: str = None) -> str: ...
```

**设计要点**:
- 按 `chat_name` 分片为独立 jsonl 文件，避免单文件过大
- 不实现去重逻辑，去重由 `ChatSession` 负责
- 详细设计见 `LOGGING_DESIGN.md`

---

## 四、关键设计决策

### 4.1 为什么去重放在 Session 而不是 Storage？

- **Storage** 负责持久化，关心的是"这条消息要不要存"
- **Session** 负责业务状态，关心的是"这条消息要不要回复"
- 循环发送的根因是"业务决策错误"，不是"存储错误"

### 4.2 为什么 LayoutParser 不做过滤？

- 时间戳是不是"消息"，取决于业务定义
- Layout 只负责"这是时间戳元素"，不决定"要不要忽略"
- 这样 MessageExtractor 可以灵活处理（比如某些场景需要保留时间戳）

### 4.3 为什么用 `SentMessage` 而不是 `last_reply_content` 字符串？

- 字符串匹配只能判断内容是否相同，无法记录发送时间和上下文
- `SentMessage` 包含 `sent_at`，支持基于时间窗口的回声检测
- 聊天滚动时 Y 坐标不可靠，因此去重放弃了坐标匹配，改用**窗口指纹 + 上下文序列**判断重复视图
- `SentMessage` 列表支持连续发送多条消息后的回声检测

### 4.4 为什么当前只支持单聊天循环？

- macOS 微信**没有稳定的原生快捷键**用于在不同聊天间切换（`Command+F` 搜索结果不可靠，上下箭头需要已知列表位置）
- 当前 `MessageSender` 只依赖键盘事件，不需要坐标；但切换聊天必须依赖**坐标点击**
- 因此多聊天支持需要新增 `UIInteractor`（坐标点击）+ 扩展 `VisionPipeline` 提供聊天列表坐标，属于明确的下一阶段扩展点

---

## 五、扩展点

### 5.1 支持其他 IM 软件

只需新增：
1. `LayoutProfile`（钉钉/飞书的布局配置）
2. `MessageSender`（不同软件的发送方式）

Capture、OCR、Session、Reply 全部复用。

### 5.2 支持多分辨率自动适配

```python
class ProfileSelector:
    def select(self, window_rect: Rect) -> LayoutProfile:
        """根据窗口尺寸自动匹配最接近的 profile"""
```

### 5.3 支持图片/语音消息识别

在 `MessageExtractor` 中增加：
- 图片检测（通过 OCR 的 `[图片]` 文本标记）
- 语音检测（通过 `[语音]` 文本标记 + 时长元素）

### 5.4 支持多聊天切换回复

当前架构仅支持"单聊天循环"。要支持多聊天，需要：

1. **Action 层新增 `UIInteractor`**：
   ```python
   class UIInteractor:
       def click_chat_item(self, item: ChatListItem) -> bool: ...
   ```
2. **Bot 层调整主循环**：
   - 先 `perception.perceive()` 获取左侧聊天列表（`result.chat_list_items`）
   - Bot 层决策后，通过 `ui_interactor.click_chat_item(item)` 切换到目标聊天
   - 再执行一次 `perception.perceive()` 获取该聊天最新消息，然后回复

**原则**：坐标操作完全封装在 Action `UIInteractor` 中；`VisionPipeline` 只负责感知，不承担任何交互动作。

### 5.5 支持 Bot 层外部集成（如 OpenClaw / MCP）

当前 `WeChatBot` 是自包含的闭环系统（`tick()` → `run_auto()`），没有外部集成接口。

要对接外部 Agent 系统（如 OpenClaw），需在 L5 Bot 层增加以下扩展：

1. **事件出口：`on_message` 回调**
   ```python
   class WeChatBot:
       def __init__(self, ..., on_message=None):
           self.on_message = on_message  # 推送新消息给外部系统
   ```
   在 `tick()` 中识别到 `new_messages` 后，通过 `on_message(msg, session)` 把事件流推出去。

2. **外部入口：`send_to_chat()` 主动发送**
   ```python
   def send_to_chat(self, chat_name: str, text: str) -> ActionResult:
       """外部系统调用此接口主动发消息到指定聊天。"""
   ```

3. **替换回复生成器**
   `ReplyGenerator` 的接口已经是抽象的，可通过注入不同的 `llm_client` 实现：
   - 本地 LLM（默认 `KimiClient`）
   - 远程 Agent Client（OpenClaw）
   - 规则引擎/固定回复

**更远的未来**：可把 `WeChatBot` 包装为 MCP Server，提供工具 `send_wechat_message` 和资源 `wechat://recent_messages/{chat_name}`。

---

## 六、错误处理策略

| 层级 | 错误场景 | 处理方式 |
|------|---------|---------|
| Capture | 未找到窗口 | 跳过本轮，sleep interval |
| OCR | 无文本识别 | 继续执行，返回空列表 |
| Layout | 无法提取 chat_name | 跳过回复，尝试切换到未读聊天 |
| Session | 检测到回声消息 | `filter_new()` 过滤掉，不回复 |
| Generator | LLM 调用失败 | 返回兜底文案 "收到" |
| Sender | AppleScript 失败 | 返回 `ActionResult(success=False)`，不重试 |

**原则**: 任何一层失败都不应该让整个系统崩溃，应该优雅降级。

---

## 七、文件结构（目标）

```
wechat-mac-rpa/
├── wechat_rpa/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── base.py              # Point, Rect, ChatMessage, etc.
│   ├── capture/
│   │   ├── __init__.py
│   │   └── window_capture.py
│   ├── ocr/
│   │   ├── __init__.py
│   │   └── vision_ocr.py
│   ├── layout/
│   │   ├── __init__.py
│   │   ├── profile.py
│   │   └── layout_parser.py
│   ├── message/
│   │   ├── __init__.py
│   │   └── extractor.py
│   ├── session/
│   │   ├── __init__.py
│   │   └── chat_session.py
│   ├── reply/
│   │   ├── __init__.py
│   │   ├── policy.py
│   │   └── generator.py
│   ├── action/
│   │   ├── __init__.py
│   │   ├── message_sender.py
│   │   └── ui_interactor.py
│   ├── perception/
│   │   ├── __init__.py
│   │   └── vision_pipeline.py   # 视觉感知管道
│   ├── bot/
│   │   ├── __init__.py
│   │   └── wechat_bot.py        # 主循环
│   ├── logging/
│   │   ├── __init__.py
│   │   └── bot_logger.py
│   └── storage/
│       ├── __init__.py
│       └── chat_history.py
├── tests/
│   ├── fixtures/
│   │   ├── errors/              # 错误用例库
│   │   └── current.png
│   ├── test_capture.py
│   ├── test_ocr.py
│   ├── test_layout.py
│   ├── test_message.py
│   ├── test_session.py
│   ├── test_sender.py
│   ├── test_bot.py
│   ├── test_logging.py          # BotLogger 测试
│   └── test_chat_history.py     # ChatHistory 测试
├── ARCHITECTURE.md              # 本文档
├── LOGGING_DESIGN.md            # 日志与历史记录设计
└── LESSONS_LEARNED.md
```

---

**最后更新**: 2026-04-17
**文档状态**: 已覆盖全部模块，重构已完成
**状态**: ✅ L1-L5 模块化架构已全部落地，`auto_bot_vision_ocr_v4.py` 已拆分为 `wechat_rpa/` 目录下的独立模块，旧 V2/V3/V4 文件已删除
