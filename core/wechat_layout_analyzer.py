#!/usr/bin/env python3
"""
微信界面布局分析器
结合颜色、坐标、方向精确识别界面元素
"""

import cv2
import numpy as np
from PIL import Image
from dataclasses import dataclass
from typing import List, Tuple, Optional
import json

@dataclass
class LayoutElement:
    """界面元素"""
    x: int
    y: int
    width: int
    height: int
    element_type: str      # 'title' | 'avatar' | 'bubble_self' | 'bubble_other' | 
                           # 'nickname' | 'message_text' | 'timestamp' | 'input_area'
    color_rgb: Tuple[int, int, int]
    confidence: float = 0.0
    text: str = ""

@dataclass  
class ChatMessage:
    """识别出的消息"""
    sender_id: str
    sender_type: str       # 'self' | 'other'
    content: str
    timestamp: str
    bubble_box: Tuple[int, int, int, int]  # x, y, w, h


class WeChatLayoutAnalyzer:
    """微信界面布局分析器"""
    
    # 微信界面颜色定义 (RGB)
    COLORS = {
        'self_bubble': np.array([95, 220, 95]),      # 自己消息气泡 - 绿色
        'other_bubble': np.array([230, 230, 230]),   # 对方消息气泡 - 灰色
        'background': np.array([250, 250, 250]),     # 背景 - 白色
        'title_bar': np.array([248, 248, 248]),      # 标题栏
        'input_area': np.array([237, 237, 238]),     # 输入框区域
        'divider': np.array([220, 220, 220]),        # 分割线
    }
    
    def __init__(self):
        self.image = None
        self.img_array = None
        self.height = 0
        self.width = 0
        
    def load(self, image_path: str):
        """加载截图"""
        self.image = Image.open(image_path).convert('RGB')
        self.img_array = np.array(self.image)
        self.height, self.width = self.img_array.shape[:2]
        
    def analyze_layout(self) -> dict:
        """完整布局分析"""
        return {
            'chat_name': self.extract_chat_name(),
            'my_avatar_pos': self.find_my_avatar(),
            'message_bubbles': self.find_message_bubbles(),
            'messages': self.extract_messages(),
        }
    
    def extract_chat_name(self) -> str:
        """
        提取聊天对象名称
        位置：顶部标题栏中央，y < 50
        特征：水平居中，文字较长
        """
        # 标题栏区域 (顶部 5%)
        title_region = self.img_array[5:50, :, :]
        
        # 使用 OCR 或颜色分割找到文字
        # 简化：找与背景色不同的区域
        bg_color = self.COLORS['title_bar']
        diff = np.abs(title_region.astype(int) - bg_color.astype(int))
        mask = np.sum(diff, axis=2) > 30  # 与背景差异大的像素
        
        # 找水平投影（有文字的位置）
        h_proj = np.sum(mask, axis=0)
        text_cols = np.where(h_proj > 5)[0]
        
        if len(text_cols) > 0:
            # 找最长的连续文字区域（在中间）
            mid = self.width // 2
            # 简化返回
            return "需要OCR提取"
        
        return "未知"
    
    def find_my_avatar(self) -> Optional[Tuple[int, int]]:
        """
        找到自己头像位置
        特征：绿色气泡旁边的圆形头像，在右侧
        """
        # 找绿色气泡
        green_mask = self._color_mask(self.COLORS['self_bubble'], tolerance=50)
        
        # 找连通区域
        contours = self._find_contours(green_mask, min_area=1000)
        
        if contours:
            # 取最右边的绿色气泡
            rightmost = max(contours, key=lambda c: cv2.boundingRect(c)[0])
            x, y, w, h = cv2.boundingRect(rightmost)
            # 头像在气泡右侧
            avatar_x = x + w + 10
            avatar_y = y + h // 2
            return (avatar_x, avatar_y)
        
        return None
    
    def find_message_bubbles(self) -> List[LayoutElement]:
        """
        找到所有消息气泡
        策略：
        1. 绿色区域 = 自己消息
        2. 灰色圆角矩形 = 对方消息
        3. 通过边缘检测辅助
        """
        bubbles = []
        
        # 1. 找绿色气泡（自己）
        green_mask = self._color_mask(self.COLORS['self_bubble'], tolerance=60)
        green_contours = self._find_contours(green_mask, min_area=2000, max_area=50000)
        
        for cnt in green_contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # 过滤不合理的
            if self._is_valid_bubble(x, y, w, h, 'self'):
                roi = self.img_array[y:y+h, x:x+w]
                avg_color = tuple(np.mean(roi, axis=(0,1)).astype(int))
                bubbles.append(LayoutElement(
                    x=x, y=y, width=w, height=h,
                    element_type='bubble_self',
                    color_rgb=avg_color
                ))
        
        # 2. 找灰色气泡（对方）- 更难，需要边缘检测
        # 先用边缘检测找所有可能的矩形
        gray = cv2.cvtColor(self.img_array, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        
        # 膨胀连接边缘
        kernel = np.ones((5,5), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=2)
        
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 2000 or area > 60000:
                continue
            
            x, y, w, h = cv2.boundingRect(cnt)
            
            # 检查是否是灰色气泡
            if self._is_valid_bubble(x, y, w, h, 'other'):
                # 检查内部颜色
                inner = self.img_array[y+5:y+h-5, x+5:x+w-5]
                if inner.size > 0:
                    avg_color = np.mean(inner, axis=(0,1))
                    # 灰色特征：RGB相近，值在200-245之间
                    r, g, b = avg_color
                    is_gray = abs(r-g) < 15 and abs(g-b) < 15 and 200 < r < 245
                    
                    if is_gray:
                        bubbles.append(LayoutElement(
                            x=x, y=y, width=w, height=h,
                            element_type='bubble_other',
                            color_rgb=(int(r), int(g), int(b))
                        ))
        
        # 按 y 坐标排序
        bubbles.sort(key=lambda b: b.y)
        return bubbles
    
    def extract_messages(self) -> List[ChatMessage]:
        """提取完整消息列表"""
        bubbles = self.find_message_bubbles()
        messages = []
        
        for bubble in bubbles:
            # OCR 气泡内容
            content = self._ocr_bubble(bubble)
            
            # 找发送者
            sender = self._find_sender(bubble)
            
            messages.append(ChatMessage(
                sender_id=sender,
                sender_type='self' if bubble.element_type == 'bubble_self' else 'other',
                content=content,
                timestamp="",
                bubble_box=(bubble.x, bubble.y, bubble.width, bubble.height)
            ))
        
        return messages
    
    def _is_valid_bubble(self, x, y, w, h, bubble_type) -> bool:
        """检查是否是有效的消息气泡"""
        # 尺寸检查
        if w < 50 or h < 30 or w > 800 or h > 400:
            return False
        
        # 宽高比检查
        aspect = w / h
        if aspect < 0.3 or aspect > 8:
            return False
        
        # 位置检查
        if y < self.height * 0.1:  # 不在标题栏
            return False
        if y > self.height * 0.9:  # 不在输入区
            return False
        
        # 自己消息在右侧，对方在左侧
        center_x = x + w // 2
        if bubble_type == 'self' and center_x < self.width * 0.5:
            return False  # 自己消息应该在右侧
        if bubble_type == 'other' and center_x > self.width * 0.7:
            return False  # 对方消息应该在左侧
        
        return True
    
    def _color_mask(self, target_color: np.ndarray, tolerance: int) -> np.ndarray:
        """创建颜色掩码"""
        lower = np.maximum(target_color - tolerance, 0)
        upper = np.minimum(target_color + tolerance, 255)
        return np.all((self.img_array >= lower) & (self.img_array <= upper), axis=2).astype(np.uint8) * 255
    
    def _find_contours(self, mask: np.ndarray, min_area: int = 1000, max_area: int = 50000):
        """查找连通区域"""
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return [c for c in contours if min_area <= cv2.contourArea(c) <= max_area]
    
    def _ocr_bubble(self, bubble: LayoutElement) -> str:
        """OCR 识别气泡内容"""
        # 这里简化，实际应调用 Vision OCR
        return f"[气泡内容 x={bubble.x},y={bubble.y}]"
    
    def _find_sender(self, bubble: LayoutElement) -> str:
        """查找发送者昵称"""
        # 在气泡上方区域查找
        search_y = max(0, bubble.y - 40)
        search_h = min(35, bubble.y - search_y)
        
        if search_h < 10:
            return "未知"
        
        # 简化返回
        return "待OCR识别"
    
    def visualize(self, output_path: str = "/tmp/wechat_layout_visualization.png"):
        """可视化分析结果"""
        vis = self.img_array.copy()
        
        # 画气泡框
        bubbles = self.find_message_bubbles()
        for b in bubbles:
            color = (0, 255, 0) if b.element_type == 'bubble_self' else (200, 200, 200)
            cv2.rectangle(vis, (b.x, b.y), (b.x+b.width, b.y+b.height), color, 2)
            cv2.putText(vis, b.element_type, (b.x, b.y-5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
        # 画区域分界线
        h = self.height
        cv2.line(vis, (0, int(h*0.08)), (self.width, int(h*0.08)), (255, 0, 0), 1)
        cv2.putText(vis, "标题栏", (10, int(h*0.06)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 1)
        
        cv2.line(vis, (0, int(h*0.88)), (self.width, int(h*0.88)), (255, 0, 0), 1)
        cv2.putText(vis, "输入区", (10, int(h*0.92)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 1)
        
        # 保存
        Image.fromarray(vis).save(output_path)
        return output_path


if __name__ == "__main__":
    analyzer = WeChatLayoutAnalyzer()
    analyzer.load("/tmp/wechat_ocr.png")
    
    print("=" * 60)
    print("🔍 微信界面布局分析")
    print("=" * 60)
    
    result = analyzer.analyze_layout()
    
    print(f"\n聊天对象: {result['chat_name']}")
    print(f"自己头像位置: {result['my_avatar_pos']}")
    print(f"消息气泡数: {len(result['message_bubbles'])}")
    
    print("\n气泡列表:")
    for i, b in enumerate(result['message_bubbles'][-10:], 1):
        icon = "🟢" if b.element_type == 'bubble_self' else "⚪"
        print(f"  {i}. {icon} {b.element_type} ({b.x},{b.y}) {b.width}x{b.height}")
    
    # 生成可视化
    vis_path = analyzer.visualize()
    print(f"\n可视化结果: {vis_path}")
