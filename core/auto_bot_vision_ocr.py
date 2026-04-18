#!/usr/bin/env python3
"""
基于 macOS Vision 框架的微信 RPA 机器人（全自动方案）

核心流程：
1. 每 3 秒截图微信窗口
2. 使用 macOS Vision 框架识别文字（Apple Silicon 原生，无需 PyTorch）
3. 提取最新消息（窗口底部区域）
4. AI 生成回复
5. 自动发送
"""

import time
import subprocess
import os
import sys
import re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_client import KimiClient

# macOS Vision 框架
import Vision
import Quartz
from Foundation import NSURL, NSArray


class WeChatVisionOCRBot:
    """基于 macOS Vision 的微信机器人"""
    
    def __init__(self):
        self.lang = 'zh-Hans'  # 中文简体
        self.llm = KimiClient()
        self.last_message = ""
        self.last_reply = ""
        self.running = False
        self.system_prompt = """你是微信智能助手，请遵守以下规则：
1. 回复简洁，适合微信阅读
2. 适当使用 emoji 增加亲和力
3. 技术问题给出代码示例
4. 不知道时诚实说不知道
5. 不要回复过长的内容"""
        
        # 截图保存路径
        self.screenshot_path = "/tmp/wechat_ocr.png"
        
        # 系统消息过滤模式
        self.system_patterns = [
            re.compile(r'\[图片\]|\[视频\]|\[语音\]|\[文件\]|\[动画表情\]'),
            re.compile(r'撤回了一条消息|邀请你加入群聊|拍了拍'),
            re.compile(r'https?://\S+'),
            re.compile(r'^\d{2}:\d{2}$'),  # 时间戳
            re.compile(r'今天|昨天|星期[一二三四五六日]'),
        ]
        
        # 消息冷却期（秒）：同一消息 30 秒内不重复回复
        self.cooldown_seconds = 30
        self.replied_history = {}  # {消息内容: 上次回复时间戳}
        
    def ocr_with_vision(self, image_path):
        """使用 macOS Vision 框架进行 OCR"""
        # 创建识别请求
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLanguages_(NSArray.arrayWithObject_(self.lang))
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)
        
        # 加载图片
        image_url = NSURL.fileURLWithPath_(image_path)
        image_source = Quartz.CGImageSourceCreateWithURL(image_url, None)
        
        if image_source is None:
            return []
        
        cg_image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)
        if cg_image is None:
            return []
        
        # 创建处理句柄
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
        
        # 执行识别
        success, error = handler.performRequests_error_([request], None)
        
        if not success:
            print(f"OCR 失败: {error}")
            return []
        
        # 提取结果
        results = []
        for observation in request.results():
            text = str(observation.text())
            confidence = float(observation.confidence())
            bbox = observation.boundingBox()  # CGRect (origin.x, origin.y, size.width, size.height)
            
            # Vision 的坐标系：左下角为原点，需要转换
            results.append({
                'text': text,
                'confidence': confidence,
                'x': float(bbox.origin.x),
                'y': float(bbox.origin.y),
                'width': float(bbox.size.width),
                'height': float(bbox.size.height),
            })
        
        return results
    
    def get_wechat_window(self):
        """获取微信窗口位置和大小（使用 Quartz，避免 AppleScript 权限问题）"""
        try:
            import Quartz
            
            window_list = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID
            )
            
            for window in window_list:
                owner = window.get(Quartz.kCGWindowOwnerName, '')
                # 匹配 WeChat 或 微信
                if owner in ('WeChat', '微信'):
                    bounds = window.get(Quartz.kCGWindowBounds, {})
                    width = int(bounds.get('Width', 0))
                    height = int(bounds.get('Height', 0))
                    # 过滤小窗口，只保留主聊天窗口（> 200x200）
                    if width > 200 and height > 200:
                        return {
                            'x': int(bounds.get('X', 0)),
                            'y': int(bounds.get('Y', 0)),
                            'width': width,
                            'height': height
                        }
            return None
        except Exception as e:
            print(f"获取窗口失败: {e}")
            return None
    
    def capture_wechat(self):
        """截图微信窗口"""
        win = self.get_wechat_window()
        if not win:
            return None
        
        try:
            cmd = [
                'screencapture',
                '-R', f"{win['x']},{win['y']},{win['width']},{win['height']}",
                '-x',
                self.screenshot_path
            ]
            subprocess.run(cmd, check=True, timeout=5)
            
            # 同时保存带时间戳的副本，方便追溯
            import shutil
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            archive_path = f"/tmp/wechat_ocr_{timestamp}.png"
            shutil.copy2(self.screenshot_path, archive_path)
            
            return win
        except Exception as e:
            print(f"截图失败: {e}")
            return None
    
    def extract_messages(self, image_path, win_height):
        """从截图中提取消息"""
        if not os.path.exists(image_path):
            return []
        
        try:
            results = self.ocr_with_vision(image_path)
            
            messages = []
            for r in results:
                text = r['text'].strip()
                if len(text) < 2:
                    continue
                    
                # Vision 的 y 坐标是左下角原点，转换为顶部原点
                top_y = 1.0 - r['y'] - r['height']
                center_x = r['x'] + r['width'] / 2
                
                messages.append({
                    'text': text,
                    'confidence': r['confidence'],
                    'y': top_y,  # 归一化坐标（0=顶部，1=底部）
                    'center_x': center_x,  # 归一化坐标
                })
            
            return messages
        except Exception as e:
            print(f"OCR 失败: {e}")
            return []
    
    def get_latest_message(self, messages):
        """获取最新消息（窗口底部，y 坐标最小的）"""
        if not messages:
            return None
        
        # Vision 的 y 坐标：归一化后，0=顶部，1=底部
        # 最新消息在底部，y 值最大
        messages.sort(key=lambda x: x['y'], reverse=True)
        
        # 排除输入框区域（底部约 15%）
        # 同时过滤系统消息
        valid = []
        for m in messages:
            if m['y'] < 0.85:  # 排除底部 15%（输入框）
                if not any(p.search(m['text']) for p in self.system_patterns):
                    valid.append(m)
        
        return valid[0] if valid else None
    
    def is_user_message(self, msg):
        """判断是否是对方消息（左侧）"""
        # 微信布局：对方消息在左侧（x < 0.55），自己消息在右侧（x > 0.55）
        # 微信对方消息气泡可能延伸到中间，所以阈值不能太低
        return msg['center_x'] < 0.55
    
    def should_reply(self, text):
        """判断是否需要回复"""
        if not text or len(text.strip()) < 2:
            return False
        
        # 过滤系统消息
        for pattern in self.system_patterns:
            if pattern.search(text):
                return False
        
        # 过滤自己的上一条回复（精确匹配，避免 AI 回复包含用户关键词导致误判）
        if text == self.last_reply:
            return False
        
        # 检查冷却期
        now = time.time()
        last_replied = self.replied_history.get(text, 0)
        if now - last_replied < self.cooldown_seconds:
            return False
        
        return True
    
    def generate_reply(self, message):
        """生成回复"""
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤔 AI 思考中...")
            reply = self.llm.chat('wechat_user', message, self.system_prompt)
            return reply
        except Exception as e:
            print(f"❌ AI 失败: {e}")
            return "抱歉，我这边有点问题 😅"
    
    def focus_wechat(self):
        """聚焦微信"""
        try:
            # 使用 open 命令激活（比 AppleScript 更可靠）
            subprocess.run(['open', '-a', 'WeChat'], capture_output=True, timeout=3)
        except:
            pass
        time.sleep(0.3)
    
    def send_message(self, message):
        """发送消息"""
        self.focus_wechat()
        time.sleep(0.2)
        
        try:
            subprocess.run(['pbcopy'], input=message.encode(), timeout=2)
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
            subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5)
            
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"[{timestamp}] ✉️ 已发送: {message[:60]}{'...' if len(message) > 60 else ''}")
            
            self.last_reply = message
            
        except Exception as e:
            print(f"发送失败: {e}")
    
    def run(self, interval=3.0):
        """运行机器人"""
        print("=" * 60)
        print("🤖 微信 Vision OCR RPA 机器人（全自动）")
        print("=" * 60)
        print()
        print("使用 macOS Vision 框架，Apple Silicon 原生优化")
        print()
        
        print("✅ 初始化完成，开始运行")
        print(f"检查间隔: {interval} 秒")
        print("按 Ctrl+C 停止")
        print()
        
        self.running = True
        cycle = 0
        
        try:
            while self.running:
                cycle += 1
                timestamp = datetime.now().strftime('%H:%M:%S')
                
                # 检查微信是否运行
                result = subprocess.run(['pgrep', 'WeChat'], capture_output=True, timeout=5)
                if result.returncode != 0:
                    time.sleep(interval)
                    continue
                
                # 激活微信
                self.focus_wechat()
                time.sleep(0.5)
                
                # 截图并获取窗口信息
                win = self.capture_wechat()
                if not win:
                    time.sleep(interval)
                    continue
                
                # OCR 识别
                messages = self.extract_messages(self.screenshot_path, win['height'])
                
                if not messages:
                    if cycle % 10 == 0:
                        print(f"[{timestamp}] ⏳ 未检测到文字")
                    time.sleep(interval)
                    continue
                
                # 获取最新消息
                latest = self.get_latest_message(messages)
                if not latest:
                    time.sleep(interval)
                    continue
                
                text = latest['text']
                is_user = self.is_user_message(latest)
                
                # 只在消息变化时打印识别结果
                is_new_message = text != self.last_message
                
                # 只回复对方消息
                if is_user and self.should_reply(text):
                    self.last_message = text
                    print(f"[{timestamp}] 👁️ 新消息: '{text[:50]}...' (置信度: {latest['confidence']:.2f})")
                    
                    reply = self.generate_reply(text)
                    
                    if reply:
                        print(f"[{timestamp}] 💬 AI: {reply[:80]}{'...' if len(reply) > 80 else ''}")
                        self.send_message(reply)
                        # 记录回复时间和内容
                        self.replied_history[text] = time.time()
                elif is_user:
                    # 对方消息，但 should_reply 返回 False
                    if is_new_message:
                        self.last_message = text
                        last_replied = self.replied_history.get(text, 0)
                        if last_replied > 0:
                            remaining = self.cooldown_seconds - (time.time() - last_replied)
                            print(f"[{timestamp}] ⏭️  冷却期内({max(0, remaining):.0f}s)，跳过: '{text[:40]}...'")
                        else:
                            print(f"[{timestamp}] ⏭️  已过滤，跳过: '{text[:40]}...'")
                elif not is_user:
                    # 只打印一次自己的消息
                    if is_new_message:
                        self.last_message = text
                        print(f"[{timestamp}] ⏭️  自己的消息，跳过")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 机器人已停止")
            self.running = False


if __name__ == "__main__":
    bot = WeChatVisionOCRBot()
    bot.run(interval=3.0)
