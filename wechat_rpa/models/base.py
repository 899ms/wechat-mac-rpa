#!/usr/bin/env python3
"""L1 Domain Models - 基础数据类型"""

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
    """领域模型：一条聊天消息（自带回复状态）"""
    text: str
    sender: str
    sender_type: SenderType
    chat_name: str
    is_at_me: bool = False
    timestamp: Optional[str] = None
    source_elements: Optional[List[OCRTextElement]] = None

    # === 消息级回复状态 ===
    replied: bool = False              # 是否已回复
    reply_text: str = ""              # 回复内容
    reply_time: Optional[float] = None # 回复时间戳

    # === 图片/表情相关 ===
    message_type: str = "text"         # "text" / "image" / "sticker" / "mixed" / "link_card"
    image_description: str = ""        # 视觉模型对图片内容的描述
    image_text: str = ""               # 图片上的文字（如有）


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
    window_rect: Optional[Rect] = None  # 窗口屏幕逻辑坐标
    scale_factor: float = 1.0  # Retina 缩放因子
    debug_info: Optional[Dict] = None  # 完整调试信息（tick 级）
