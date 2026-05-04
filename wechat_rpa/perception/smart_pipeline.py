#!/usr/bin/env python3
"""L3.5 Smart Vision Pipeline - 本地预判 + qwen3.6-flash API 兜底

架构:
    截图 → 像素差异判断 ──无变化──→ 本地 LayoutParser(chat_list) + 空 messages
                    │
                    └──有变化──→ 本地 LayoutParser(chat_list) + qwen3.6-flash(messages)

优势:
    - 92.6% 的 tick 无需调用 API（基于 69 张连续截图评测）
    - 消息提取准确率从本地 OCR 的 ~60% 提升到 qwen3.6-flash 的 ~83%
    - 群聊昵称识别、emoji、换行格式全部保留
"""

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from wechat_rpa.models.base import ChatListItem, ChatMessage, PerceptionResult, Rect, SenderType
from wechat_rpa.capture.window_capture import WindowCapture, WeChatNotReadyError
from wechat_rpa.ocr.vision_ocr import VisionOCREngine
from wechat_rpa.layout.layout_parser import LayoutParser
from wechat_rpa.layout.profile import LayoutProfile
from wechat_rpa.action.login_recovery import WeChatLoginHandler

_logger = logging.getLogger("wechat_rpa.runtime.smart_pipeline")

# ---------------------------------------------------------------------------
# Qwen3.6-flash API 客户端（轻量封装，避免循环导入 benchmark 脚本）
# ---------------------------------------------------------------------------

import base64
import json as _json
import time


def _load_env():
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


_load_env()

QWEN_SYSTEM_PROMPT = """你是一位专精 UI 截图文字识别的 OCR 引擎。请仔细识别这张微信 Mac 版截图中的文字信息，并输出为 JSON。

截图包含以下区域：
1. 左侧聊天列表：每个条目包含头像、昵称、最后一条消息预览时间、未读角标数字（红色圆形背景）
2. 中间上方标题栏：当前聊天名称
3. 中间消息区域：消息按对话顺序从上到下排列

请严格按以下 JSON 格式输出（不要加 markdown 代码块，直接输出纯 JSON）：

{
  "chat_name": "当前聊天名称，如果没有则空字符串",
  "chat_list": [
    {"nickname": "昵称1", "unread_count": "未读数量，没有则为空字符串"},
    {"nickname": "昵称2", "unread_count": "3"}
  ],
  "messages": [
    {"sender": "自己", "text": "消息内容", "type": "text"},
    {"sender": "对方", "text": "私聊中对方的消息", "type": "text"},
    {"sender": "群成员昵称", "text": "群聊中对方的消息", "type": "text"},
    {"sender": "对方", "text": "", "type": "image", "image_description": "一只橘猫趴在键盘上", "image_text": "不想上班"},
    {"sender": "对方", "text": "", "type": "sticker", "image_description": "熊猫头流泪的表情包", "image_text": ""}
  ]
}

【关键识别规则 - 必须严格遵守】

1. 未读角标（unread_count）：
   - 必须是红色圆形背景中的白色/黑色数字，位于头像右上角
   - 预览消息右侧的时间戳（如"09:31"、"昨天"、"00:57"）是消息时间，不是未读角标，unread_count 必须设为空字符串""
   - 如果没有红色圆形数字，unread_count 为空字符串""

2. 聊天列表（chat_list）：
   - 【重要】chat_list 必须严格按照截图中左侧列表从上到下的顺序排列，第一个就是截图中最顶部的条目
   - 左侧每个条目提取昵称，忽略头像区域的所有数字（除非是红色圆形未读角标）
   - 当前高亮选中的聊天条目也必须包含
   - 预览消息文字不要放入 nickname

3. 消息 sender 判断（这是最容易出错的地方，请仔细看气泡颜色和布局）：
   - 【最重要】气泡颜色是判断 sender 的第一依据：
     - 绿色背景的气泡 = "自己" 发送的消息，sender 必须填 "自己"
     - 白色或浅灰色背景的气泡 = 对方发送的消息，sender 填 "对方"（私聊）或群成员昵称（群聊）
   - 【绝对不能搞反】白色气泡绝对不是自己发的，绿色气泡绝对不是对方发的
   - 【群聊 vs 私聊区分】
     - 群聊：消息气泡上方会显示发送者昵称 → sender 必须填这个实际昵称
     - 私聊：只有两个人，消息气泡上方不显示发送者昵称 → sender 必须填 "对方"
   - 绝对不能把私聊中的对方消息填成群成员昵称或具体人名
   - 辅助判断（颜色看不清时用）：右侧对齐的气泡是自己，左侧对齐的气泡是对方
   - 时间戳（如"昨天 21:58"、"11:34"、"00:22"）不是消息，不要输出
   - 【常见错误】不要把白色气泡的对方消息错标为 "自己"，也不要把短消息默认当成自己发的

4. 消息 type 分类（重要新增）：
   - "text"：纯文字消息（含 emoji 符号）
   - "image"：图片、照片、截图等非表情类的图像内容
   - "sticker"：表情包、动图、微信自带表情、表情商店下载的表情
   - "mixed"：图文混排（消息同时包含图片和文字）
   - "link_card"：链接卡片、文章分享、小程序卡片
   - 判断标准：看消息气泡里的主要内容。如果气泡内主要是图像且几乎没有文字 → image/sticker；如果主要是文字 → text
   - 区分 image 和 sticker：表情包通常尺寸较小、风格卡通、配简短文字；照片/截图通常尺寸较大、内容写实

5. 图片/表情识别（重要新增）：
   - 如果消息是图片或表情包，text 字段放图片上的文字（如有），没有则空字符串
   - image_description：详细描述图片/表情包的内容。例如：
     - 照片："夕阳下的海滩，天空呈现橙红色，有几只海鸥"
     - 表情包："一只熊猫头流泪，配文'我太难了'"
     - 截图："手机截图，显示微信聊天界面"
   - image_text：图片上叠加的文字（如表情包配字、截图中的文字、照片上的水印文字）
   - 【隐私保护】如果图片包含身份证、银行卡、地址、电话号码等隐私信息，image_description 简化为"[图片-包含隐私信息]"
   - 【隐私保护】如果图片包含裸露、暴力等不适宜内容，image_description 简化为"[图片]"
   - 链接卡片（link_card）的 image_description 描述卡片外观（如"分享了一篇公众号文章，标题为xxx"），image_text 提取卡片上的标题和摘要

6. 消息（messages）：
   - 包含所有消息：文字、图片、表情包、链接卡片
   - 排除所有时间戳
   - 按截图中从上到下顺序排列

7. 输入框过滤（重要）：
   - 截图最底部是输入框区域（有表情😊、文件📎、截图✂️、语音🎤按钮）
   - 输入框中的文字是未发送的草稿，不是已发送的消息，必须排除
   - 不要输出输入框中的任何内容

8. 只输出 JSON，不要任何解释文字。
"""


class _QwenAPIClient:
    """轻量级 qwen3.6-flash API 客户端，只保留核心调用逻辑。"""

    def __init__(self, api_key: Optional[str] = None, model: str = "qwen3.6-flash"):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
        self.model = model
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY not set")
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package required: pip install openai")
        self._client = OpenAI(
            api_key=self.api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def recognize(self, image_path: str) -> dict:
        raw, _, _ = self.recognize_with_debug(image_path)
        return raw

    def recognize_with_debug(self, image_path: str) -> tuple:
        """识别并返回 (parsed_result, prompt, raw_response)。"""
        b64 = self._image_to_base64(image_path)
        prompt = QWEN_SYSTEM_PROMPT
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ]
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.0,
            max_tokens=4096,
            extra_body={"enable_thinking": False},
        )
        raw = response.choices[0].message.content or ""
        return self._extract_json(raw), prompt, raw

    @staticmethod
    def _image_to_base64(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return _json.loads(text)


# ---------------------------------------------------------------------------
# Image Description Dedup Tracker - 基于描述相似度的图片去重
# ---------------------------------------------------------------------------

from collections import deque
from difflib import SequenceMatcher


class ImageDedupTracker:
    """基于描述文本相似度的图片去重器。

    策略：同一聊天、同一发送者在时间窗口内，如果图片描述相似度超过阈值，
    视为重复图片/表情包，避免 Bot 对同一张图反复反应。
    """

    def __init__(self, window_seconds: float = 60.0, similarity_threshold: float = 0.2):
        self._entries: deque = deque()  # (chat_name, sender, description, timestamp)
        self.window_seconds = window_seconds
        self.similarity_threshold = similarity_threshold

    def is_duplicate(self, chat_name: str, sender: str, description: str) -> bool:
        """检查是否为重复图片。"""
        if not description or description.startswith("["):
            # 隐私保护标记或空描述，不参与去重判断
            return False

        now = time.time()
        # 清理过期条目
        while self._entries and now - self._entries[0][3] > self.window_seconds:
            self._entries.popleft()

        for cn, s, desc, _ in self._entries:
            if cn == chat_name and s == sender:
                sim = self._similarity(desc, description)
                if sim >= self.similarity_threshold:
                    return True
        return False

    def add(self, chat_name: str, sender: str, description: str):
        """记录一张图片的描述。"""
        if not description or description.startswith("["):
            return
        self._entries.append((chat_name, sender, description, time.time()))

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """计算两段描述文本的相似度，0.0~1.0。

        使用 2-gram Jaccard 系数，对中文图片描述更稳健。
        SequenceMatcher 对长中文文本过于敏感（公共字符/量词导致误判），
        2-gram Jaccard 基于"共同出现的相邻字对"，能更好区分不同图片。
        """
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        # 生成 2-gram 集合
        ba = set(a[i:i + 2] for i in range(len(a) - 1))
        bb = set(b[i:i + 2] for i in range(len(b) - 1))
        inter = len(ba & bb)
        union = len(ba | bb)
        return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# SmartPerceptionPipeline
# ---------------------------------------------------------------------------

class SmartPerceptionPipeline:
    """智能感知管道：本地预判 + qwen3.6-flash API 兜底。

    与 VisionPipeline 接口完全兼容（duck typing），可直接替换。
    """

    # 消息区域像素差异阈值（0.001 = 0.1%）
    # 原值 0.005 导致大量无实质变化的截图触发 API，烧钱过快
    DEFAULT_PIXEL_DIFF_THRESHOLD = 0.001
    # 消息区域 ROI（相对坐标 x1, y1, x2, y2），排除左侧列表和底部输入框
    DEFAULT_MESSAGE_REGION = (0.35, 0.12, 0.95, 0.85)
    # 窗口最小有效尺寸（小于此值视为异常，如登录浮窗）
    MIN_WINDOW_WIDTH = 800
    MIN_WINDOW_HEIGHT = 600

    def __init__(
        self,
        profile: LayoutProfile,
        api_key: Optional[str] = None,
        pixel_diff_threshold: float = DEFAULT_PIXEL_DIFF_THRESHOLD,
        message_region: tuple = DEFAULT_MESSAGE_REGION,
        always_use_api: bool = False,
    ):
        self.capture = WindowCapture(login_handler=WeChatLoginHandler())
        self.ocr = VisionOCREngine()
        self.layout = LayoutParser(profile)
        self.profile = profile

        # API 客户端（延迟初始化，失败时优雅降级）
        self._api_client: Optional[_QwenAPIClient] = None
        self._api_key = api_key
        self._api_available: Optional[bool] = None

        # 像素差异判断状态
        self.pixel_diff_threshold = pixel_diff_threshold
        self.message_region = message_region
        self.always_use_api = always_use_api
        self._last_screenshot: Optional[Path] = None
        self._last_hash: Optional[str] = None

        # 连续低差异计数：连续 N 帧差异 < 阈值，进入稳定模式进一步降低阈值
        self._consecutive_low_diff = 0
        self._stable_mode_threshold = pixel_diff_threshold * 0.5
        self._stable_mode_after = 3  # 连续 3 帧低差异后触发

        # 统计
        self.api_call_count = 0
        self.skip_count = 0
        self.local_fallback_count = 0

        # 图片去重跟踪器
        self.image_dedup = ImageDedupTracker(window_seconds=60.0, similarity_threshold=0.2)

    # -----------------------------------------------------------------------
    # 公共接口（与 VisionPipeline.perceive 签名一致）
    # -----------------------------------------------------------------------

    def perceive(self) -> Optional[PerceptionResult]:
        """执行完整视觉链路，带本地预判优化。

        Returns:
            PerceptionResult: 结构化结果
            None: 窗口捕获失败或尺寸异常
        """
        _logger.info("[SmartPipeline] perceive() 开始")

        # 1. 截图
        try:
            capture_result = self.capture.capture()
        except WeChatNotReadyError as e:
            _logger.warning(f"[SmartPipeline] 窗口捕获失败: {e}")
            return None
        except Exception as e:
            _logger.warning(f"[SmartPipeline] 窗口捕获异常: {e}")
            return None

        image_path = capture_result.image_path
        window_rect = capture_result.window_rect
        scale_factor = getattr(capture_result, "scale_factor", 1.0)
        _logger.info(
            f"[SmartPipeline] 截图成功: {Path(image_path).name}, "
            f"窗口={window_rect.width}x{window_rect.height}, scale={scale_factor}"
        )

        # 2. 窗口尺寸检查（过滤登录浮窗等异常窗口）
        if window_rect.width < self.MIN_WINDOW_WIDTH or window_rect.height < self.MIN_WINDOW_HEIGHT:
            _logger.warning(
                f"[SmartPipeline] 窗口尺寸异常 ({window_rect.width}x{window_rect.height})，"
                f"小于最小阈值 ({self.MIN_WINDOW_WIDTH}x{self.MIN_WINDOW_HEIGHT})，"
                "可能处于登录/异常状态，跳过"
            )
            return None

        # 3. 像素差异判断（always_use_api 模式强制走 API）
        skip_api = False
        diff_ratio = None
        if self.always_use_api:
            _logger.info("[SmartPipeline] always_use_api=true，强制调用API（不跳过）")
        elif self._last_screenshot and self._last_screenshot.exists():
            curr_hash = self._compute_hash(image_path)
            _logger.debug(
                f"[SmartPipeline] hash对比: prev={self._last_hash[:8]}... curr={curr_hash[:8]}..."
            )
            if curr_hash == self._last_hash:
                skip_api = True
                diff_ratio = 0.0
                self._consecutive_low_diff += 1
                _logger.info(
                    f"[SmartPipeline] 截图完全相同 (hash一致)，跳过API调用"
                )
            else:
                diff_ratio = self._check_pixel_diff(str(self._last_screenshot), image_path)
                # 稳定模式：连续多帧低差异后，阈值临时降低 50%
                effective_threshold = self.pixel_diff_threshold
                if self._consecutive_low_diff >= self._stable_mode_after:
                    effective_threshold = self._stable_mode_threshold
                    _logger.info(
                        f"[SmartPipeline] 稳定模式已触发 (连续{self._consecutive_low_diff}帧低差异)，"
                        f"有效阈值降至 {effective_threshold:.6f}"
                    )
                skip_api = diff_ratio < effective_threshold
                if skip_api:
                    self._consecutive_low_diff += 1
                else:
                    self._consecutive_low_diff = 0
                _logger.info(
                    f"[SmartPipeline] 像素差异: {diff_ratio:.6f} "
                    f"(阈值={effective_threshold}), "
                    f"决策={'跳过API' if skip_api else '调用API'}"
                )
        else:
            _logger.info("[SmartPipeline] 无历史截图，首次运行，调用API")
            self._consecutive_low_diff = 0

        self._last_screenshot = Path(image_path)
        self._last_hash = self._compute_hash(image_path)

        if skip_api:
            self.skip_count += 1
            _logger.info(
                f"[SmartPipeline] 本地跳过统计: skip_count={self.skip_count}, "
                f"api_count={self.api_call_count}, "
                f"skip_rate={self.skip_count/(self.skip_count+self.api_call_count)*100:.1f}%"
            )
            return self._run_local_only(image_path, window_rect, scale_factor)

        # 4. 有变化：本地 Layout + qwen3.6-flash API（并行）
        self.api_call_count += 1
        _logger.info(
            f"[SmartPipeline] 触发API调用: api_count={self.api_call_count}, "
            f"skip_count={self.skip_count}"
        )
        return self._run_with_api(image_path, window_rect, scale_factor)

    # -----------------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # 调试信息序列化
    # -----------------------------------------------------------------------

    @staticmethod
    def _serialize_ocr_element(e):
        return {
            "text": getattr(e, "text", ""),
            "x": getattr(e.bbox, "x", 0),
            "y": getattr(e.bbox, "y", 0),
            "w": getattr(e.bbox, "width", 0),
            "h": getattr(e.bbox, "height", 0),
            "cx": getattr(e.center, "x", 0),
            "cy": getattr(e.center, "y", 0),
            "confidence": getattr(e, "confidence", 0.0),
        }

    def _serialize_layout(self, layout) -> dict:
        if layout is None:
            return {}
        info = layout.debug_info if hasattr(layout, "debug_info") else {}
        result = {
            "layout_left_elements": info.get("left_elements", []),
            "layout_right_elements": info.get("right_elements", []),
            "layout_title_elements": [self._serialize_ocr_element(e) for e in getattr(layout, "title_elements", [])],
            "layout_input_elements": [self._serialize_ocr_element(e) for e in getattr(layout, "input_elements", [])],
            "layout_timestamp_elements": [self._serialize_ocr_element(e) for e in getattr(layout, "timestamp_elements", [])],
            "layout_chat_list_nicknames": [item.nickname for item in layout.chat_list_items],
            "layout_chat_list_unread": [item.unread_count for item in layout.chat_list_items],
            "layout_message_candidates": [self._serialize_ocr_element(e) for e in layout.message_candidates],
            "layout_self_bubbles": [
                {"x": r.x, "y": r.y, "w": r.width, "h": r.height}
                for r in layout.self_bubbles
            ],
        }
        # 添加 debug_info 中的其他字段
        if "chat_list" in info:
            result["layout_chat_list_groups"] = info["chat_list"].get("groups", [])
        return result

    def _build_debug_info(self, layout, api_prompt: str = "", api_response: str = "", extraction_messages=None) -> dict:
        info = self._serialize_layout(layout)
        info["api_prompt"] = api_prompt
        info["api_response"] = api_response
        if extraction_messages is not None:
            info["extraction_messages"] = [
                {
                    "text": m.text,
                    "sender": m.sender,
                    "sender_type": m.sender_type.value if hasattr(m.sender_type, "value") else m.sender_type,
                    "chat_name": m.chat_name,
                    "type": m.message_type,
                    "image_description": m.image_description,
                    "image_text": m.image_text,
                    "is_image_duplicate": m.is_image_duplicate,
                }
                for m in extraction_messages
            ]
        return info

    def _run_local_only(
        self, image_path: str, window_rect: Rect, scale_factor: float
    ) -> PerceptionResult:
        """无变化时：只跑本地 LayoutParser，messages 为空。"""
        _logger.info("[SmartPipeline] 进入本地路径(跳过API)")
        t0 = time.time()
        elements = self.ocr.recognize(image_path)
        layout = self.layout.parse(elements, image_path)
        local_ms = (time.time() - t0) * 1000
        _logger.info(
            f"[SmartPipeline] 本地处理完成: chat_name='{layout.chat_name}', "
            f"chat_list={len(layout.chat_list_items)}项, "
            f"messages=0条(跳过), "
            f"耗时={local_ms:.0f}ms"
        )
        debug_info = self._build_debug_info(layout)
        return PerceptionResult(
            chat_name=layout.chat_name or "",
            messages=[],
            chat_list_items=layout.chat_list_items,
            screenshot_path=image_path,
            window_rect=window_rect,
            scale_factor=scale_factor,
            debug_info=debug_info,
        )

    def _build_chat_list_items_from_api(
        self, api_chat_list: list, window_width: int, window_height: int, chat_name: str
    ) -> list:
        """从 API 返回的 chat_list 构建 ChatListItem，使用基于索引的虚拟 rect。

        固定坐标规则（基于 1738x1602 Retina 截图实测）：
        - 左侧边栏宽约 55px，聊天列表从 x=55 开始
        - 搜索栏高约 50px，列表起始 y = 50
        - 每个列表项高度 = 75
        - 列表宽度：右侧展开时 ~35%，折叠时 ~85%
        
        注意：window_width/height 传入的是截图实际像素（Retina），不是逻辑像素。
        """
        items = []
        is_expanded = bool(chat_name)
        sidebar_width = 55
        list_start_x = sidebar_width
        list_width = int(window_width * 0.35) if is_expanded else int(window_width * 0.85)
        list_start_y = 50
        item_height = 75

        for i, item in enumerate(api_chat_list):
            item_y = list_start_y + i * item_height
            rect = Rect(x=list_start_x, y=item_y, width=list_width, height=item_height)
            items.append(
                ChatListItem(
                    nickname=item.get("nickname", ""),
                    last_message_preview="",
                    unread_count=item.get("unread_count", ""),
                    timestamp="",
                    rect=rect,
                )
            )
        return items

    def _run_with_api(
        self, image_path: str, window_rect: Rect, scale_factor: float
    ) -> PerceptionResult:
        """有变化时：API 负责消息提取和昵称识别，本地 Layout 负责聊天列表定位。"""
        _logger.info("[SmartPipeline] 进入API路径")
        t0 = time.time()

        # 1. 并行跑本地 OCR + Layout（用于获取聊天列表的准确位置）
        local_t0 = time.time()
        try:
            local_result = self._run_local_pipeline(image_path)
            layout = local_result["layout"]
            local_chat_list = layout.chat_list_items
            local_ms = (time.time() - local_t0) * 1000
            _logger.info(f"[SmartPipeline] 本地Layout完成: chat_list={len(local_chat_list)}项, 耗时={local_ms:.0f}ms")
        except Exception as e:
            _logger.warning(f"[SmartPipeline] 本地Layout失败: {e}")
            layout = None
            local_chat_list = []

        # 2. 调用 API（用于准确识别昵称、未读数、消息内容）
        api_result = self._run_api_pipeline(image_path)

        api_messages = api_result.get("messages", [])
        api_chat_name = api_result.get("chat_name", "")
        api_chat_list = api_result.get("chat_list", [])
        api_prompt = api_result.get("prompt", "")
        api_response = api_result.get("response", "")

        # 过滤误识别的未读角标（时间戳、群人数等）
        for item in api_chat_list:
            raw = item.get("unread_count", "")
            if not raw:
                continue
            # 包含冒号 → 时间戳（如"10:23"）
            if ":" in raw:
                item["unread_count"] = ""
                continue
            # 包含汉字 → 时间描述（如"昨天"）
            if any("\u4e00" <= c <= "\u9fff" for c in raw):
                item["unread_count"] = ""
                continue
            # 不是纯数字 → 误识别
            if not raw.isdigit():
                item["unread_count"] = ""
                continue
            # 数字过大 → 群人数等误识别（微信未读角标最大99）
            if int(raw) > 99:
                item["unread_count"] = ""
                continue

        # 3. 结合：本地 Layout 提供准确 rect，API 提供准确 nickname/unread_count
        chat_list_items = self._merge_chat_list(local_chat_list, api_chat_list)

        messages = self._convert_api_messages(api_messages, api_chat_name)

        total_ms = (time.time() - t0) * 1000
        _logger.info(
            f"[SmartPipeline] 完成: chat_name='{api_chat_name}', "
            f"messages={len(messages)}条, chat_list={len(chat_list_items)}项, "
            f"耗时={total_ms:.0f}ms"
        )
        if messages:
            for i, m in enumerate(messages):
                preview = m.text[:40].replace(chr(10), '\\n')
                _logger.debug(f"  msg[{i}] sender={m.sender} type={m.sender_type.value} text='{preview}...'")

        debug_info = self._build_debug_info(layout, api_prompt, api_response, messages)
        debug_info["api_chat_list"] = api_chat_list
        return PerceptionResult(
            chat_name=api_chat_name,
            messages=messages,
            chat_list_items=chat_list_items,
            screenshot_path=image_path,
            window_rect=window_rect,
            scale_factor=scale_factor,
            debug_info=debug_info,
        )

    def _merge_chat_list(
        self, local_chat_list: list, api_chat_list: list
    ) -> list:
        """结合本地 Layout 的准确位置和 API 的准确昵称/未读数。

        策略：
        1. 本地 chat_list 按 y 坐标排序（截图从上到下）
        2. API chat_list 理论上也应该从上到下，但不可靠
        3. 如果数量相同，按索引一一对应（本地提供 rect，API 提供 nickname/unread）
        4. 如果数量不同，用昵称模糊匹配
        """
        if not local_chat_list:
            # 本地 Layout 失败，回退到纯虚拟坐标
            _logger.warning("[SmartPipeline] 本地Layout无chat_list，回退到虚拟坐标")
            return self._build_chat_list_items_from_api(api_chat_list, 1738, 1602, "")

        # 本地按 y 坐标排序（确保从上到下）
        sorted_local = sorted(local_chat_list, key=lambda item: item.rect.y)

        # 如果数量相同，直接按索引对应
        if len(sorted_local) == len(api_chat_list):
            result = []
            for local_item, api_item in zip(sorted_local, api_chat_list):
                result.append(
                    ChatListItem(
                        nickname=api_item.get("nickname", local_item.nickname),
                        last_message_preview=local_item.last_message_preview,
                        unread_count=api_item.get("unread_count", local_item.unread_count),
                        timestamp=local_item.timestamp,
                        rect=local_item.rect,
                    )
                )
            return result

        # 数量不同：用昵称模糊匹配
        _logger.warning(
            f"[SmartPipeline] chat_list数量不匹配: 本地={len(sorted_local)}, API={len(api_chat_list)}, "
            f"使用昵称模糊匹配"
        )
        result = []
        for local_item in sorted_local:
            best_match = None
            best_score = 0.0
            for api_item in api_chat_list:
                nickname = api_item.get("nickname", "")
                score = self._lcs_similarity(local_item.nickname, nickname)
                if score > best_score:
                    best_score = score
                    best_match = api_item
            if best_match and best_score >= 0.5:
                result.append(
                    ChatListItem(
                        nickname=best_match.get("nickname", local_item.nickname),
                        last_message_preview=local_item.last_message_preview,
                        unread_count=best_match.get("unread_count", local_item.unread_count),
                        timestamp=local_item.timestamp,
                        rect=local_item.rect,
                    )
                )
            else:
                result.append(local_item)
        return result

    def _lcs_similarity(self, a: str, b: str) -> float:
        """最长公共子序列相似度。"""
        if not a or not b:
            return 0.0
        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
        lcs_len = dp[m][n]
        return 2 * lcs_len / (m + n) if (m + n) > 0 else 0.0

    def _run_local_pipeline(self, image_path: str) -> dict:
        """本地 OCR + Layout 解析。"""
        elements = self.ocr.recognize(image_path)
        layout = self.layout.parse(elements, image_path)
        return {"layout": layout, "elements": elements}

    def _run_api_pipeline(self, image_path: str) -> dict:
        """调用 qwen3.6-flash API。"""
        client = self._get_api_client()
        if client is None:
            _logger.warning("[SmartPipeline] API客户端不可用，跳过API调用")
            return {}
        t0 = time.time()
        _logger.info(f"[SmartPipeline] API请求开始: model=qwen3.6-flash, image={Path(image_path).name}")
        try:
            raw, prompt, response_text = client.recognize_with_debug(image_path)
            latency_ms = (time.time() - t0) * 1000
            _logger.info(
                f"[SmartPipeline] API请求成功: latency={latency_ms:.0f}ms, "
                f"chat_name='{raw.get('chat_name', '')}', "
                f"messages={len(raw.get('messages', []))}, "
                f"chat_list={len(raw.get('chat_list', []))}"
            )
            return {
                "chat_name": raw.get("chat_name", ""),
                "messages": raw.get("messages", []),
                "chat_list": raw.get("chat_list", []),
                "prompt": prompt,
                "response": response_text,
            }
        except Exception as e:
            latency_ms = (time.time() - t0) * 1000
            _logger.error(f"[SmartPipeline] API请求失败({latency_ms:.0f}ms): {e}")
            return {}

    def _get_api_client(self) -> Optional[_QwenAPIClient]:
        """延迟初始化 API 客户端，失败时返回 None。"""
        if self._api_available is False:
            return None
        if self._api_client is not None:
            return self._api_client
        try:
            self._api_client = _QwenAPIClient(api_key=self._api_key)
            self._api_available = True
            _logger.info("qwen3.6-flash API 客户端初始化成功")
            return self._api_client
        except Exception as e:
            self._api_available = False
            _logger.error(f"API 客户端初始化失败: {e}")
            return None

    # -----------------------------------------------------------------------
    # 像素差异计算
    # -----------------------------------------------------------------------

    @staticmethod
    def _compute_hash(path: str) -> str:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _check_pixel_diff(self, prev_path: str, curr_path: str) -> float:
        """计算消息区域像素差异比例。"""
        try:
            prev = np.array(Image.open(prev_path).convert("RGB"), dtype=np.int16)
            curr = np.array(Image.open(curr_path).convert("RGB"), dtype=np.int16)
        except Exception:
            return 1.0  # 出错时视为有变化

        if prev.shape != curr.shape:
            return 1.0  # 尺寸变化视为有变化

        h, w = curr.shape[:2]
        x1, y1, x2, y2 = self.message_region
        region = (
            slice(int(y1 * h), int(y2 * h)),
            slice(int(x1 * w), int(x2 * w)),
        )

        diff = np.abs(curr[region] - prev[region])
        diff_mask = np.any(diff > 10, axis=2)  # RGB 任一通道差异 > 10
        diff_ratio = float(np.mean(diff_mask))
        return diff_ratio

    # -----------------------------------------------------------------------
    # 结果转换
    # -----------------------------------------------------------------------

    def _convert_api_messages(self, raw_messages: list, chat_name: str) -> list[ChatMessage]:
        """将 API 返回的 messages 转换为 ChatMessage 列表。

        支持图片/表情包识别和去重。
        """
        messages = []
        for m in raw_messages:
            sender = m.get("sender", "")
            text = m.get("text", "")
            msg_type = m.get("type", "text") or "text"
            image_description = m.get("image_description", "") or ""
            image_text = m.get("image_text", "") or ""

            if sender == "自己":
                sender_type = SenderType.SELF
            elif sender in ("对方", ""):
                sender_type = SenderType.OTHER
                sender = "对方"
            else:
                # 群聊昵称或其他 sender
                sender_type = SenderType.OTHER

            # 图片/表情/链接卡片：允许 text 为空
            is_media = msg_type in ("image", "sticker", "mixed", "link_card")
            if not text and not is_media:
                continue

            # 图片去重：同一聊天同一 sender 在短时间内发送相似图片
            is_dup = False
            if msg_type in ("image", "sticker") and image_description:
                if self.image_dedup.is_duplicate(chat_name, sender, image_description):
                    is_dup = True
                else:
                    self.image_dedup.add(chat_name, sender, image_description)

            messages.append(
                ChatMessage(
                    text=text,
                    sender=sender,
                    sender_type=sender_type,
                    chat_name=chat_name,
                    message_type=msg_type,
                    image_description=image_description,
                    image_text=image_text,
                    is_image_duplicate=is_dup,
                )
            )
        return messages

    def get_stats(self) -> dict:
        """返回统计信息。"""
        total = self.api_call_count + self.skip_count
        return {
            "total_ticks": total,
            "api_calls": self.api_call_count,
            "skipped": self.skip_count,
            "local_fallbacks": self.local_fallback_count,
            "api_ratio": round(self.api_call_count / total, 3) if total > 0 else 0,
        }
