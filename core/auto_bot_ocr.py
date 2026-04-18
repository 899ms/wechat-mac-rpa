#!/usr/bin/env python3
"""
基于 OCR 的微信 RPA 机器人（全自动方案）

核心流程：
1. 每 3 秒截图微信窗口
2. 使用 easyocr 识别文字
3. 提取最新消息（窗口底部区域）
4. AI 生成回复
5. 自动发送
"""

import time
import subprocess
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_client import KimiClient


class WeChatOCRBot:
    """基于 OCR 的微信机器人"""
    
    def __init__(self):
        print("⏳ 正在加载 OCR 模型（首次需要 10-20 秒）...")
        self.reader = None  # 延迟加载
        self.lang_list = ['ch_sim']  # 只使用中文模型，不需要下载 latin
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
        
    def init_ocr(self):
        """初始化 OCR（延迟加载）"""
        if self.reader is None:
            import easyocr
            self.reader = easyocr.Reader(self.lang_list, gpu=False)
            print("✅ OCR 模型加载完成")
    
    def get_wechat_window(self):
        """获取微信窗口位置和大小（使用 AppleScript）"""
        try:
            script = '''
            tell application "System Events"
                tell process "WeChat"
                    set winList to every window
                    repeat with w in winList
                        set winPos to position of w
                        set winSize to size of w
                        set winW to item 1 of winSize
                        set winH to item 2 of winSize
                        -- 找到最大的窗口（主聊天窗口）
                        if winW > 500 and winH > 400 then
                            return (item 1 of winPos) & "," & (item 2 of winPos) & "," & winW & "," & winH
                        end if
                    end repeat
                end tell
            end tell
            return ""
            '''
            result = subprocess.run(['osascript', '-e', script], 
                                  capture_output=True, text=True, timeout=5)
            
            if result.stdout.strip():
                # 清理 AppleScript 输出（去除空格和多余逗号）
                cleaned = result.stdout.strip().replace(' ', '').replace(',,', ',')
                parts = [p for p in cleaned.split(',') if p]
                if len(parts) >= 4:
                    return {
                        'x': int(parts[0]),
                        'y': int(parts[1]),
                        'width': int(parts[2]),
                        'height': int(parts[3])
                    }
            return None
        except Exception as e:
            print(f"获取窗口失败: {e}")
            return None
    
    def capture_wechat(self):
        """截图微信窗口"""
        win = self.get_wechat_window()
        if not win:
            return False
        
        try:
            # 截图指定区域
            cmd = [
                'screencapture',
                '-R', f"{win['x']},{win['y']},{win['width']},{win['height']}",
                '-x',  # 不播放声音
                self.screenshot_path
            ]
            subprocess.run(cmd, check=True, timeout=5)
            return True
        except Exception as e:
            print(f"截图失败: {e}")
            return False
    
    def extract_messages(self, image_path):
        """从截图中提取消息"""
        if not os.path.exists(image_path):
            return []
        
        try:
            # OCR 识别
            results = self.reader.readtext(image_path)
            
            # 解析结果
            messages = []
            for (bbox, text, conf) in results:
                if conf > 0.5 and len(text.strip()) > 1:  # 过滤低置信度和短文本
                    # 计算文字中心位置
                    x_coords = [p[0] for p in bbox]
                    center_x = sum(x_coords) / len(x_coords)
                    
                    messages.append({
                        'text': text.strip(),
                        'confidence': conf,
                        'center_x': center_x,
                        'bbox': bbox
                    })
            
            return messages
        except Exception as e:
            print(f"OCR 失败: {e}")
            return []
    
    def get_latest_message(self, messages):
        """获取最新消息（窗口底部，y坐标最大的）"""
        if not messages:
            return None
        
        # 按 y 坐标排序（底部优先）
        # easyocr 的 bbox: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
        def get_bottom_y(msg):
            bbox = msg['bbox']
            return max(p[1] for p in bbox)
        
        messages.sort(key=get_bottom_y, reverse=True)
        
        # 获取底部区域的消息（最新消息）
        # 排除输入框区域（假设输入框在底部 80px）
        valid_messages = []
        for msg in messages:
            bottom_y = get_bottom_y(msg)
            # 假设窗口高度 600+，输入框在底部，排除底部 100px
            # 这里简化处理，取 y 坐标最大的前几条
            valid_messages.append(msg)
        
        if not valid_messages:
            return None
        
        # 返回置信度最高的底部消息
        return max(valid_messages, key=lambda x: x['confidence'])
    
    def is_user_message(self, msg, window_width):
        """判断是否是对方消息（左侧）"""
        # 对方消息在左侧，自己的消息在右侧
        # 简单判断：x < 宽度/2 认为是对方消息
        return msg['center_x'] < window_width * 0.6
    
    def should_reply(self, text):
        """判断是否需要回复"""
        if not text or len(text.strip()) < 2:
            return False
        
        # 过滤系统消息
        skip_keywords = ['[图片]', '[视频]', '[语音]', '[文件]', '[动画表情]', 
                        '撤回了一条消息', '今天', '昨天', '星期']
        for kw in skip_keywords:
            if kw in text:
                return False
        
        # 过滤自己的上一条回复（避免循环）
        if text == self.last_reply or text in self.last_reply:
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
        subprocess.run(['osascript', '-e', 'tell application "WeChat" to activate'], 
                      capture_output=True, timeout=5)
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
            
            # 记录上一条回复，用于去重
            self.last_reply = message
            
        except Exception as e:
            print(f"发送失败: {e}")
    
    def run(self, interval=3.0):
        """运行机器人"""
        print("=" * 60)
        print("🤖 微信 OCR RPA 机器人（全自动）")
        print("=" * 60)
        print()
        print("⚠️  首次启动需要 10-20 秒加载 OCR 模型")
        print()
        
        # 初始化 OCR
        self.init_ocr()
        
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
                
                # 激活微信（确保窗口在最前面）
                self.focus_wechat()
                time.sleep(0.5)
                
                # 截图
                if not self.capture_wechat():
                    time.sleep(interval)
                    continue
                
                # OCR 识别
                messages = self.extract_messages(self.screenshot_path)
                
                if not messages:
                    if cycle % 10 == 0:  # 每 10 轮打印一次心跳
                        print(f"[{timestamp}] ⏳ 未检测到文字")
                    time.sleep(interval)
                    continue
                
                # 获取最新消息
                latest = self.get_latest_message(messages)
                if not latest:
                    time.sleep(interval)
                    continue
                
                text = latest['text']
                
                # 获取窗口宽度用于判断消息方向
                win = self.get_wechat_window()
                win_width = win['width'] if win else 800
                
                # 判断是否是对方消息
                is_user = self.is_user_message(latest, win_width)
                
                print(f"[{timestamp}] 👁️ 识别: '{text[:50]}...' (置信度: {latest['confidence']:.2f}, 对方: {is_user})")
                
                # 只回复对方消息
                if is_user and self.should_reply(text):
                    # 避免重复回复
                    if text != self.last_message:
                        self.last_message = text
                        
                        # 生成回复
                        reply = self.generate_reply(text)
                        
                        if reply:
                            print(f"[{timestamp}] 💬 AI: {reply[:80]}{'...' if len(reply) > 80 else ''}")
                            self.send_message(reply)
                    else:
                        print(f"[{timestamp}] ⏭️  已回复过")
                else:
                    if not is_user:
                        print(f"[{timestamp}] ⏭️  自己的消息，跳过")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 机器人已停止")
            self.running = False


if __name__ == "__main__":
    bot = WeChatOCRBot()
    bot.run(interval=3.0)
