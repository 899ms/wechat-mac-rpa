#!/usr/bin/env python3
"""
微信界面解析器

将 OCR 结果解析为结构化的聊天数据
"""

import re
import numpy as np
from scipy import ndimage
from PIL import Image
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from pathlib import Path

from ..ocr.vision_ocr import OCRElement


@dataclass
class ChatItem:
    """左侧聊天列表的一项"""
    nickname: str = ""
    last_message: str = ""
    unread_count: str = ""
    timestamp: str = ""


@dataclass
class ChatMessage:
    """聊天消息"""
    text: str = ""
    sender: str = ""          # 发送者昵称
    sender_type: str = "other"  # 'self' | 'other'
    is_at_me: bool = False
    timestamp: str = ""
    confidence: float = 0.0
    y_position: int = 0       # y坐标，用于排序


@dataclass
class ChatLayout:
    """完整布局"""
    chat_name: str = ""
    chat_items: List[ChatItem] = field(default_factory=list)
    messages: List[ChatMessage] = field(default_factory=list)
    is_group: bool = False


class WeChatParser:
    """微信界面解析器"""
    
    # 布局常量
    LEFT_BOUNDARY = 420        # 左右区域分界线（左侧聊天列表最大约400，右侧从约500开始）
    TITLE_Y_MAX = 50           # 顶部标题栏高度（收紧，避免包含窗口控制按钮图标）
    TITLE_X_MAX_RATIO = 0.70   # 标题栏最大x比例（排除右侧图标区域如搜索、电话按钮）
    INPUT_Y_MIN = 1120         # 底部输入区起始
    
    # 颜色阈值
    SELF_GREEN = np.array([176, 240, 167])
    SELF_TOLERANCE = 35
    
    # 昵称识别区域
    NICKNAME_X_MIN = 0.30
    NICKNAME_X_MAX = 0.55
    
    # 系统账号
    SYSTEM_ACCOUNTS = ['文件传输助手', '腾讯新闻', '微信团队']
    
    # 质量阈值
    CONFIDENCE_THRESHOLD = 0.5   # 置信度低于此值的丢弃（过滤乱码/头像干扰）
    
    # 时间戳识别
    TIMESTAMP_PATTERNS = [
        r'^\d{2}:\d{2}$',           # 00:04
        r'^\d{2}:\d{2}:\d{2}$',     # 00:04:30
        r'^昨天\s*\d{1,2}:\d{2}$',   # 昨天 23:24
        r'^星期[一二三四五六日]$',    # 星期六
        r'^\d{4}年\d{1,2}月\d{1,2}日$',  # 2024年1月1日
    ]
    TIMESTAMP_X_MIN_RATIO = 0.25  # 时间戳x最小比例（在消息区域中央）
    TIMESTAMP_X_MAX_RATIO = 0.75  # 时间戳x最大比例
    
    def __init__(self, image_width: int = 1760, image_height: int = 1280):
        self.image_width = image_width
        self.image_height = image_height
    
    def parse(self, ocr_elements: List[OCRElement], image_path: str) -> ChatLayout:
        """
        解析 OCR 结果
        
        Args:
            ocr_elements: OCR 识别出的元素列表
            image_path: 原始图片路径
            
        Returns:
            ChatLayout 结构化数据
        """
        layout = ChatLayout()
        
        # 第一步：质量过滤 - 丢弃低置信度元素（乱码/头像干扰）
        filtered_elements = self._filter_low_quality(ocr_elements)
        
        # 第二步：时间戳过滤
        filtered_elements = self._filter_timestamps(filtered_elements)
        
        # 分离左右区域
        left_elements = [e for e in filtered_elements if e.x < self.LEFT_BOUNDARY]
        right_elements = [e for e in filtered_elements if e.x >= self.LEFT_BOUNDARY]
        
        # 解析聊天列表
        layout.chat_items = self._parse_chat_list(left_elements)
        
        # 解析右侧聊天
        layout.chat_name, layout.messages, layout.is_group = self._parse_chat_area(
            right_elements, image_path
        )
        
        return layout
    
    def _filter_low_quality(self, elements: List[OCRElement]) -> List[OCRElement]:
        """过滤低质量/乱码元素（头像干扰、图标识别错误等）"""
        filtered = []
        for e in elements:
            # 置信度检查
            if e.confidence < self.CONFIDENCE_THRESHOLD:
                continue
            # 乱码模式检查（包含过多特殊字符或无意义组合）
            if self._is_garbage_text(e.text):
                continue
            filtered.append(e)
        return filtered
    
    def _is_garbage_text(self, text: str) -> bool:
        """判断是否为乱码/无意义文本"""
        if not text:
            return True
        # 包含注册商标等符号
        if any(c in text for c in ['®', '©', '™']):
            return True
        # 包含过多无意义字符（如 "QS.", "WJiPu八AJ Z" 这种随机组合）
        # 检测是否包含过多拉丁字母乱码
        if len(text) > 3:
            latin_chars = sum(1 for c in text if c.isascii() and c.isalpha())
            if latin_chars > 3 and any(c in text for c in ['⑧', '③', '米']):
                return True
        return False
    
    def _filter_timestamps(self, elements: List[OCRElement]) -> List[OCRElement]:
        """过滤时间戳元素"""
        filtered = []
        for e in elements:
            # 检查是否匹配时间戳模式
            is_timestamp = any(re.match(p, e.text) for p in self.TIMESTAMP_PATTERNS)
            if is_timestamp:
                # 额外检查位置：时间戳通常在消息区域中央
                x_ratio = e.normalized_x
                if self.TIMESTAMP_X_MIN_RATIO <= x_ratio <= self.TIMESTAMP_X_MAX_RATIO:
                    continue  # 过滤掉这个时间戳
            filtered.append(e)
        return filtered
    
    def _parse_chat_list(self, elements: List[OCRElement]) -> List[ChatItem]:
        """解析左侧聊天列表"""
        items = []
        
        # 过滤顶部，按 y 排序
        elems = [e for e in elements if e.y > 50]
        elems.sort(key=lambda e: e.y)
        
        # 昵称对齐列 x≈230
        nick_col = [e for e in elems if 210 <= e.x <= 260]
        nick_col.sort(key=lambda e: e.y)
        
        if not nick_col:
            return items
        
        # 按 y 间隔分组
        groups = []
        current = [nick_col[0]]
        for i in range(1, len(nick_col)):
            if nick_col[i].y - nick_col[i-1].y < 50:
                current.append(nick_col[i])
            else:
                groups.append(current)
                current = [nick_col[i]]
        groups.append(current)
        
        # 构建 ChatItem
        for group in groups:
            item = ChatItem()
            item.nickname = group[0].text
            if len(group) > 1:
                item.last_message = group[1].text
            
            # 未读数字
            for e in elems:
                if e.x < 80 and abs(e.y - group[0].y) < 50:
                    if e.text.isdigit():
                        item.unread_count = e.text
            
            # 时间戳
            for e in elems:
                if 260 <= e.x <= 330 and abs(e.y - group[0].y) < 30:
                    if re.match(r'^\d{2}:\d{2}$', e.text):
                        item.timestamp = e.text
            
            items.append(item)
        
        return items
    
    def _parse_chat_area(self, elements: List[OCRElement], image_path: str) -> Tuple[str, List[ChatMessage], bool]:
        """解析右侧聊天区域"""
        # 提取聊天名称（y < TITLE_Y_MAX 且 x < 宽度的 TITLE_X_MAX_RATIO 比例，排除右侧图标区域）
        title_x_max = self.image_width * self.TITLE_X_MAX_RATIO
        title_elems = [e for e in elements if e.y < self.TITLE_Y_MAX and e.x < title_x_max]
        chat_name = ""
        is_group = False
        
        if title_elems:
            # 选择最长文本作为聊天名称，并过滤掉明显不是名称的字符
            filtered = [e for e in title_elems if not any(c in e.text for c in ['®', '©', '™', 'QS'])]
            if filtered:
                best = max(filtered, key=lambda e: len(e.text))
            else:
                best = max(title_elems, key=lambda e: len(e.text))
            chat_name = best.text
            match = re.search(r'(.+?)[\(（](\d+)[\)）]', chat_name)
            if match:
                is_group = True
                chat_name = match.group(1).strip()
        
        # 加载图片用于颜色检测（确保 RGB）
        img = Image.open(image_path)
        if img.mode == 'RGBA':
            arr = np.array(img)
            arr = arr[:, :, :3]  # 去掉 Alpha 通道
        else:
            img = img.convert('RGB')
            arr = np.array(img)
        
        # 检测绿色气泡（自己消息）
        self_bubbles = self._detect_green_bubbles(arr)
        
        # 收集消息区文本（排除标题栏和已识别的聊天名称）
        title_texts = {e.text for e in title_elems}  # 标题栏文本集合
        msg_texts = []
        for e in elements:
            if self.TITLE_Y_MAX <= e.cy < self.INPUT_Y_MIN:
                text = e.text
                if text in title_texts:
                    continue  # 跳过标题文本
                if not re.match(r'^\d{2}:\d{2}$', text) and text not in self.SYSTEM_ACCOUNTS:
                    msg_texts.append(e)
        
        # 解析消息
        messages = self._parse_messages(msg_texts, self_bubbles, elements)
        
        return chat_name, messages, is_group
    
    def _detect_green_bubbles(self, arr: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """检测绿色气泡"""
        # 处理 RGBA 格式（转换为 RGB）
        if arr.shape[2] == 4:
            arr = arr[:, :, :3]
        
        diff = np.abs(arr.astype(int) - self.SELF_GREEN.astype(int))
        mask = np.all(diff < self.SELF_TOLERANCE, axis=2)
        
        labeled, num = ndimage.label(mask)
        
        bubbles = []
        for i in range(1, num + 1):
            ys, xs = np.where(labeled == i)
            if len(xs) > 200:
                x1, x2 = xs.min(), xs.max()
                y1, y2 = ys.min(), ys.max()
                if (x1 > self.LEFT_BOUNDARY and 
                    y1 > self.TITLE_Y_MAX and 
                    y2 < self.INPUT_Y_MIN):
                    bubbles.append((x1, y1, x2-x1+1, y2-y1+1))
        
        return bubbles
    
    def _parse_messages(self, msg_texts: List[OCRElement], 
                       self_bubbles: List[Tuple], 
                       all_elements: List[OCRElement]) -> List[ChatMessage]:
        """解析消息"""
        messages = []
        processed = set()
        
        # 处理自己消息
        for bubble in sorted(self_bubbles, key=lambda b: b[1]):
            bx, by, bw, bh = bubble
            texts_in = []
            
            for t in msg_texts:
                key = (t.text, t.cx, t.cy)
                if key in processed:
                    continue
                if bx <= t.cx <= bx + bw and by <= t.cy <= by + bh:
                    texts_in.append(t)
                    processed.add(key)
            
            if texts_in:
                texts_in.sort(key=lambda t: t.cy)
                merged = ' '.join([t.text for t in texts_in])
                avg_conf = sum(t.confidence for t in texts_in) / len(texts_in)
                
                messages.append(ChatMessage(
                    text=merged,
                    sender="自己",
                    sender_type="self",
                    is_at_me='@' in merged,
                    confidence=avg_conf,
                    y_position=by  # 记录气泡y坐标
                ))
        
        # 处理对方消息
        other_texts = []
        for t in msg_texts:
            key = (t.text, t.cx, t.cy)
            if key not in processed:
                if t.cy < self.INPUT_Y_MIN and t.cx < self.image_width * 0.8:
                    other_texts.append(t)
        
        if other_texts:
            other_texts.sort(key=lambda t: t.cy)
            
            # 按 y 聚类
            clusters = [[other_texts[0]]]
            for t in other_texts[1:]:
                if t.cy - clusters[-1][-1].cy < 80:
                    clusters[-1].append(t)
                else:
                    clusters.append([t])
            
            # 为每个聚类识别昵称
            for cluster in clusters:
                cluster.sort(key=lambda t: t.cy)
                
                # 检查第一条是否是昵称
                first = cluster[0]
                is_nickname = (
                    self.NICKNAME_X_MIN <= first.normalized_x <= self.NICKNAME_X_MAX and
                    self._is_likely_nickname(first.text) and
                    len(cluster) > 1
                )
                
                if is_nickname:
                    nickname = first.text
                    cluster = cluster[1:]  # 移除昵称
                else:
                    nickname = "对方"
                
                if not cluster:
                    continue
                
                merged = ' '.join([t.text for t in cluster])
                avg_conf = sum(t.confidence for t in cluster) / len(cluster)
                
                messages.append(ChatMessage(
                    text=merged,
                    sender=nickname,
                    sender_type="other",
                    is_at_me='@' in merged,
                    confidence=avg_conf,
                    y_position=cluster[0].cy  # 记录聚类第一个元素的y坐标
                ))
        
        # 按y坐标排序，确保消息按时间顺序排列
        messages.sort(key=lambda m: m.y_position)
        
        return messages
    
    def _is_likely_nickname(self, text: str) -> bool:
        """判断文本是否可能是昵称"""
        if len(text) < 2 or len(text) > 20:
            return False
        if text in self.SYSTEM_ACCOUNTS:
            return False
        if re.match(r'^\d{2}:\d{2}$', text):
            return False
        if any(p in text for p in ['[图片]', '[视频]', '[语音]', '[文件]']):
            return False
        if text.startswith('http') or text.startswith('www'):
            return False
        if text.isdigit():
            return False
        return True
