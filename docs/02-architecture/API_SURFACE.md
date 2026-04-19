# API Surface 速查表

> ⚠️ **本文档描述的是目标重构架构（Target Architecture）的接口定义，当前实际代码结构与此存在差异。**
> 
> 当前实际实现请参考 `wechat_rpa/` 目录下的现有代码：`capture/window_capture.py`、`ocr/vision_ocr.py`、`parser/wechat_parser.py`、`action/reply_generator.py`、`action/message_sender.py`、`bot/wechat_bot.py`。
>
> 所有公共接口集中于此。AI 写代码前可直接复制粘贴。

---

## L1: Domain Models

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple
```

### SenderType
```python
class SenderType(Enum):
    SELF = "self"
    OTHER = "other"
    SYSTEM = "system"
    UNKNOWN = "unknown"
```

### Point
```python
@dataclass(frozen=True)
class Point:
    x: int
    y: int
```

### Rect
```python
@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int
```

### OCRTextElement
```python
@dataclass
class OCRTextElement:
    text: str
    bbox: Rect
    center: Point
    confidence: float
```

### ChatMessage
```python
@dataclass
class ChatMessage:
    text: str
    sender: str
    sender_type: SenderType  # SELF | OTHER | SYSTEM | UNKNOWN
    chat_name: str
    is_at_me: bool = False
    timestamp: Optional[str] = None
    source_elements: Optional[List[OCRTextElement]] = None  # 仅供 L3 构造和 L4 debug，Bot 层禁止读取
```

### SentMessage
```python
@dataclass
class SentMessage:
    text: str
    sent_at: float
```

### ActionResult
```python
@dataclass
class ActionResult:
    success: bool
    sent_text: Optional[str] = None
    error: Optional[str] = None
```

### PerceptionResult
```python
@dataclass
class PerceptionResult:
    chat_name: str
    messages: List[ChatMessage]
    chat_list_items: List[ChatListItem]
    screenshot_path: str
```

### ChatListItem
```python
@dataclass
class ChatListItem:
    nickname: str
    last_message_preview: str
    unread_count: str
    timestamp: str
    rect: Rect  # 列表项在屏幕上的位置，供 UIInteractor 点击使用
```

---

## L2: Capture

### WindowCapture
```python
class WindowCapture:
    def __init__(self, output_path: str = None,
                 min_effective_width: int = 800,
                 min_effective_height: int = 600): ...
    def capture(self) -> CaptureResult: ...
```

### WeChatNotReadyError
```python
class WeChatNotReadyError(Exception):
    """微信窗口尺寸异常（未登录/需扫码）时抛出"""
```

### CaptureResult
```python
@dataclass
class CaptureResult:
    image_path: str
    window_rect: Rect
    scale_factor: float
```

---

## L2: OCR

### VisionOCREngine
```python
class VisionOCREngine:
    def recognize(self, image_path: str) -> List[OCRTextElement]: ...
```

---

## L2: LayoutProfile

### LayoutProfile
```python
@dataclass
class LayoutProfile:
    name: str
    window_width: int
    window_height: int
    left_boundary: int
    chat_list_x_max: int
    title_y_max: int
    title_x_max_ratio: float
    input_y_min: int
    self_green: Tuple[int, int, int]
    self_green_tolerance: int
    min_bubble_pixels: int
    message_cluster_threshold: int
    nickname_x_min_ratio: float
    nickname_x_max_ratio: float
    nickname_y_offset_min: int
    nickname_y_offset_max: int
```

### 预配置
```python
PROFILE_WECHAT_MAC_1760X1280: LayoutProfile
```

---

## L3: LayoutParser

### LayoutParser
```python
class LayoutParser:
    def __init__(self, profile: LayoutProfile): ...
    def parse(self, elements: List[OCRTextElement], image_path: str) -> UILayout: ...
```

### UILayout
```python
@dataclass
class UILayout:
    chat_name: str
    chat_list_items: List[ChatListItem]
    title_elements: List[OCRTextElement]
    input_elements: List[OCRTextElement]
    timestamp_elements: List[OCRTextElement]
    self_bubbles: List[Rect]
    message_candidates: List[OCRTextElement]
```

---

## L3: MessageExtractor

### MessageExtractor
```python
class MessageExtractor:
    def __init__(self, profile: LayoutProfile): ...
    def extract(self, layout: UILayout) -> List[ChatMessage]: ...
```

---

## L3.5: VisionPipeline

### VisionPipeline
```python
class VisionPipeline:
    def __init__(self, profile: LayoutProfile): ...
    def perceive(self) -> Optional[PerceptionResult]: ...
```

---

## L4: ChatSession

### ChatSession
```python
class ChatSession:
    def __init__(
        self,
        chat_id: str,
        chat_name: str,
        echo_time_window: float = 10.0,
        echo_history_limit: int = 5,
    ): ...
    def filter_new(self, messages: List[ChatMessage]) -> List[ChatMessage]: ...
    def record_sent(self, text: str) -> None: ...
    def is_in_cooldown(self, seconds: float = 30.0) -> bool: ...
    # 注意：回复决策统一由 ReplyPolicy 负责，Session 只提供状态查询
```

## L4: Reply

### ReplyPolicy
```python
class ReplyPolicy:
    def should_reply(self, msg: ChatMessage, session: ChatSession) -> bool: ...
```

### ReplyGenerator
```python
class ReplyGenerator:
    def __init__(self, llm_client=None): ...
    def generate(self, msg: ChatMessage, session: ChatSession) -> str: ...
```

---

## L4: Action

### MessageSender
```python
class MessageSender:
    def send(self, text: str) -> ActionResult: ...
    def send_image(self, image_path: str) -> ActionResult: ...
    def send_file(self, file_path: str) -> ActionResult: ...
```

### WeChatMessageSender
```python
class WeChatMessageSender(MessageSender):
    def send(self, text: str) -> ActionResult: ...
    def send_image(self, image_path: str) -> ActionResult: ...
    def send_file(self, file_path: str) -> ActionResult: ...
```

### UIInteractor
```python
class UIInteractor:
    def click_chat_item(self, item: ChatListItem) -> bool: ...
    def click_input_box(self) -> bool: ...
```

### WeChatLoginHandler
```python
class LoginRecoveryStatus(Enum):
    SUCCESS = "success"
    NEEDS_PHONE_CONFIRM = "needs_phone_confirm"
    NEEDS_QRCODE = "needs_qrcode"
    NO_LOGIN_BUTTON = "no_login_button"

class LoginRecoveryResult:
    status: LoginRecoveryStatus
    message: str

class WeChatLoginHandler:
    def __init__(self, capture_output: str = "/tmp/wechat_login_capture.png",
                 login_keywords: List[str] = None,
                 min_effective_width: int = 800,
                 min_effective_height: int = 600): ...
    def handle(self) -> LoginRecoveryResult: ...
```

---

## L4: Logging

### BotLogger
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

---

## L4: ChatHistory

### HistoryRecord
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
```

### ChatHistory
```python
class ChatHistory:
    def __init__(self, storage_dir: str = None) -> None: ...
    def append_messages(self, chat_name: str, messages: List[ChatMessage], tick_id: int = 0, screenshot_path: str = "") -> List[HistoryRecord]: ...
    def get_messages(self, chat_name: Optional[str] = None, since: datetime = None, until: datetime = None, limit: int = 500) -> List[HistoryRecord]: ...
    def get_recent_chats(self, hours: float = 24.0, limit: int = 100) -> Dict[str, List[HistoryRecord]]: ...
    def get_last_message(self, chat_name: str) -> Optional[HistoryRecord]: ...
    def get_stats(self) -> dict: ...
    def export_chat(self, chat_name: str, output_path: str = None) -> str: ...
```


---

## L5: Bot

### WeChatBot
```python
class WeChatBot:
    def __init__(self, profile: LayoutProfile, on_message: Optional[Callable] = None):
        self.perception = VisionPipeline(profile)
        self.sessions: Dict[str, ChatSession] = {}
        self.policy = ReplyPolicy()
        self.generator = ReplyGenerator()
        self.sender = WeChatMessageSender()
        self.on_message = on_message
    def tick(self) -> None: ...
    def run_auto(self, interval: float = 5.0) -> None: ...
    def _get_session(self, chat_name: str) -> ChatSession: ...
    def send_to_chat(self, chat_name: str, text: str) -> ActionResult: ...
```
