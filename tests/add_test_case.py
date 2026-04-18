#!/usr/bin/env python3
"""
添加新的测试用例

用法:
    python tests/add_test_case.py <截图路径> [--name <测试名称>]

示例:
    python tests/add_test_case.py /tmp/wechat_test1.png --name group_chat
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.auto_bot_vision_ocr_v4 import WeChatVisionOCRBotV4


def add_test_case(image_path: str, test_name: str = None):
    """添加新的测试用例"""
    
    image_path = Path(image_path)
    if not image_path.exists():
        print(f"❌ 图片不存在: {image_path}")
        return False
    
    # 生成测试名称
    if not test_name:
        # 查找下一个可用的 test_XX 名称
        fixture_dir = Path("tests/fixtures")
        existing = list(fixture_dir.glob("test_*.png"))
        test_num = len(existing) + 1
        test_name = f"test_{test_num:02d}"
    
    fixture_dir = Path("tests/fixtures")
    fixture_dir.mkdir(exist_ok=True)
    
    fixture_img = fixture_dir / f"{test_name}.png"
    fixture_json = fixture_dir / f"{test_name}.json"
    
    # 复制图片
    shutil.copy2(image_path, fixture_img)
    print(f"📸 已复制截图: {fixture_img}")
    
    # 运行 OCR 生成预期结果
    print(f"🔍 运行 OCR 识别...")
    bot = WeChatVisionOCRBotV4()
    
    try:
        chat_items, messages, _, chat_name = bot.analyze(str(image_path), save_screenshot=False)
        
        expected = {
            "chat_name": chat_name,
            "chat_list": [
                {
                    "nickname": item.nickname,
                    "last_message": item.last_message,
                    "unread_count": item.unread_count
                }
                for item in chat_items
            ],
            "messages": [
                {
                    "sender": msg.sender,
                    "sender_type": msg.sender_type,
                    "text": msg.text,
                    "is_at_me": msg.is_at_me
                }
                for msg in messages
            ]
        }
        
        # 保存预期结果
        with open(fixture_json, 'w', encoding='utf-8') as f:
            json.dump(expected, f, ensure_ascii=False, indent=2)
        
        print(f"📝 已生成预期结果: {fixture_json}")
        print(f"\n📊 识别结果:")
        print(f"   聊天名称: {chat_name}")
        print(f"   聊天列表: {len(chat_items)} 个")
        print(f"   消息数量: {len(messages)} 条")
        
        print(f"\n✅ 测试用例 '{test_name}' 添加成功！")
        print(f"\n💡 提示: 请检查 {fixture_json} 文件，确保预期结果正确")
        print(f"   运行测试: python3 tests/test_ocr_v4.py")
        
        return True
        
    except Exception as e:
        print(f"❌ OCR 识别失败: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="添加微信 OCR 测试用例")
    parser.add_argument("image", help="截图文件路径")
    parser.add_argument("--name", help="测试用例名称（可选）")
    
    args = parser.parse_args()
    
    success = add_test_case(args.image, args.name)
    sys.exit(0 if success else 1)
