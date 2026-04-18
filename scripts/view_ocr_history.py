#!/usr/bin/env python3
"""
查看微信 OCR 历史识别记录
"""

import os
import re
from datetime import datetime
from pathlib import Path

LOG_FILE = "/tmp/wechat_vision_ocr.log"

def get_log_content():
    """获取日志内容"""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            return f.read()
    return ""

def extract_ocr_records(log_content):
    """从日志中提取 OCR 识别记录"""
    records = []
    
    for line in log_content.split('\n'):
        # 新消息
        match = re.search(r'\[(\d{2}:\d{2}:\d{2})\] 👁️ 新消息: \'(.+?)\' \(置信度: ([\d.]+)\)', line)
        if match:
            time_str, text, conf = match.groups()
            records.append({
                'time': time_str,
                'type': '新消息',
                'text': text,
                'confidence': float(conf)
            })
            continue
        
        # 自己消息
        match = re.search(r'\[(\d{2}:\d{2}:\d{2})\] ⏭️  自己的消息，跳过', line)
        if match:
            records.append({
                'time': match.group(1),
                'type': '自己消息',
                'text': '(AI回复)',
                'confidence': 0
            })
            continue
        
        # 冷却跳过
        match = re.search(r'\[(\d{2}:\d{2}:\d{2})\] ⏭️  冷却期内', line)
        if match:
            records.append({
                'time': match.group(1),
                'type': '冷却跳过',
                'text': '(冷却期内)',
                'confidence': 0
            })
    
    return records

def show_history():
    """显示历史 OCR 记录"""
    print("=" * 70)
    print("📜 微信 OCR 历史识别记录")
    print("=" * 70)
    print()
    
    log_content = get_log_content()
    if not log_content:
        print("❌ 暂无日志记录")
        return
    
    records = extract_ocr_records(log_content)
    
    if not records:
        print("⚠️  未找到识别记录")
        return
    
    msg_count = sum(1 for r in records if r['type'] == '新消息')
    self_count = sum(1 for r in records if r['type'] == '自己消息')
    skip_count = sum(1 for r in records if r['type'] == '冷却跳过')
    
    print(f"📊 统计: {msg_count} 条用户消息 | {self_count} 条AI回复 | {skip_count} 条冷却跳过")
    print("-" * 70)
    print()
    
    for r in records:
        icon = {'新消息': '👤', '自己消息': '🤖', '冷却跳过': '⏱️'}.get(r['type'], '•')
        if r['type'] == '新消息':
            print(f"{icon} [{r['time']}] '{r['text']}' (置信度: {r['confidence']:.2f})")
        else:
            print(f"{icon} [{r['time']}] {r['text']}")
    
    print()
    print("=" * 70)

def show_raw(lines=50):
    """显示原始日志"""
    print(f"📄 原始日志（最近 {lines} 行）")
    print("=" * 70)
    
    log_content = get_log_content()
    log_lines = log_content.split('\n')
    
    for line in log_lines[-lines:]:
        print(line)
    
    print("=" * 70)

def export():
    """导出日志"""
    log_dir = Path("/tmp/wechat_logs")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = log_dir / f"ocr_history_{timestamp}.txt"
    
    with open(export_path, 'w') as f:
        f.write(get_log_content())
    
    print(f"✅ 已导出: {export_path}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'raw':
            show_raw(int(sys.argv[2]) if len(sys.argv) > 2 else 50)
        elif sys.argv[1] == 'export':
            export()
        else:
            print("用法: python view_ocr_history.py [raw [行数] | export]")
    else:
        show_history()
