#!/usr/bin/env python3
"""
自动添加 OCR 识别错误案例

当 V4 OCR 识别出现错误时，自动保存为测试用例以便后续修复。

用法:
    from tests.auto_add_error_case import auto_add_error_case
    
    # 当检测到识别错误时
    auto_add_error_case(
        image_path="/tmp/wechat_ocr.png",
        expected_result={
            "chat_name": "群名称",
            "messages": [{"sender": "正确昵称", "text": "正确内容"}]
        },
        error_type="WRONG_SENDER",
        error_details="发送者 wanglc 被识别为 对方"
    )
"""

import os
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def auto_add_error_case(
    image_path: str,
    expected_result: dict = None,
    error_type: str = "UNKNOWN",
    error_details: str = ""
):
    """
    自动添加 OCR 识别错误案例
    
    Args:
        image_path: 错误识别的截图路径
        expected_result: 正确的预期结果（如果已知）
        error_type: 错误类型，如 WRONG_SENDER, WRONG_COUNT, LOW_SIMILARITY
        error_details: 错误详情描述
    """
    
    # 创建错误案例目录
    error_dir = Path("tests/fixtures/errors")
    error_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成错误案例编号
    existing_errors = list(error_dir.glob("error_*.png"))
    error_num = len(existing_errors) + 1
    timestamp = datetime.now().strftime("%Y%m%d")
    
    error_name = f"error_{timestamp}_{error_num:03d}"
    error_png = error_dir / f"{error_name}.png"
    error_json = error_dir / f"{error_name}.json"
    
    # 复制截图
    shutil.copy2(image_path, error_png)
    
    # 构建错误案例信息
    error_info = {
        "error_name": error_name,
        "error_type": error_type,
        "error_details": error_details,
        "created_at": datetime.now().isoformat(),
        "image_path": str(error_png),
        "status": "pending",  # pending | fixed | verified
        "expected": expected_result or {},
        "notes": ""
    }
    
    # 如果没有提供预期结果，尝试用当前 OCR 识别结果作为基础
    if not expected_result:
        from core.auto_bot_vision_ocr_v4 import WeChatVisionOCRBotV4
        
        try:
            bot = WeChatVisionOCRBotV4()
            chat_items, messages, _, chat_name = bot.analyze(image_path, save_screenshot=False)
            
            error_info["expected"] = {
                "chat_name": chat_name,
                "chat_list": [
                    {"nickname": item.nickname, "last_message": item.last_message}
                    for item in chat_items
                ],
                "messages": [
                    {"sender": msg.sender, "sender_type": msg.sender_type, 
                     "text": msg.text, "is_at_me": msg.is_at_me}
                    for msg in messages
                ]
            }
            error_info["notes"] = "⚠️  此预期结果为当前 OCR 识别结果，需要人工修正为正确值"
        except Exception as e:
            error_info["notes"] = f"⚠️  OCR 识别失败: {e}"
    
    # 保存错误信息
    with open(error_json, 'w', encoding='utf-8') as f:
        json.dump(error_info, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"⚠️  OCR 识别错误已记录")
    print(f"{'='*60}")
    print(f"错误案例: {error_name}")
    print(f"错误类型: {error_type}")
    print(f"错误详情: {error_details}")
    print(f"截图路径: {error_png}")
    print(f"信息文件: {error_json}")
    print(f"\n💡 请检查并修正 {error_json} 中的预期结果")
    print(f"   修正后运行测试: ./tests/run_tests.sh")
    print(f"{'='*60}\n")
    
    return error_name


def get_all_error_cases():
    """获取所有未修复的错误案例"""
    error_dir = Path("tests/fixtures/errors")
    if not error_dir.exists():
        return []
    
    error_cases = []
    for json_file in sorted(error_dir.glob("error_*.json")):
        with open(json_file, 'r', encoding='utf-8') as f:
            error_info = json.load(f)
        if error_info.get("status") != "fixed":
            error_cases.append((json_file.stem, error_info))
    
    return error_cases


def mark_error_fixed(error_name: str):
    """标记错误案例为已修复"""
    error_json = Path(f"tests/fixtures/errors/{error_name}.json")
    if not error_json.exists():
        print(f"❌ 错误案例不存在: {error_name}")
        return False
    
    with open(error_json, 'r', encoding='utf-8') as f:
        error_info = json.load(f)
    
    error_info["status"] = "fixed"
    error_info["fixed_at"] = datetime.now().isoformat()
    
    with open(error_json, 'w', encoding='utf-8') as f:
        json.dump(error_info, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 已标记为已修复: {error_name}")
    return True


def promote_error_to_fixture(error_name: str):
    """
    将错误案例提升为正式测试用例
    当错误案例验证通过后，移动到 fixtures/ 目录
    """
    error_dir = Path("tests/fixtures/errors")
    fixture_dir = Path("tests/fixtures")
    
    error_png = error_dir / f"{error_name}.png"
    error_json = error_dir / f"{error_name}.json"
    
    if not error_png.exists() or not error_json.exists():
        print(f"❌ 错误案例文件不存在: {error_name}")
        return False
    
    # 读取错误信息，提取预期结果
    with open(error_json, 'r', encoding='utf-8') as f:
        error_info = json.load(f)
    
    expected = error_info.get("expected", {})
    if not expected:
        print(f"❌ 错误案例没有预期结果: {error_name}")
        return False
    
    # 生成新的测试用例名称
    test_name = f"fixed_{error_name}"
    fixture_png = fixture_dir / f"{test_name}.png"
    fixture_json = fixture_dir / f"{test_name}.json"
    
    # 移动文件
    shutil.copy2(error_png, fixture_png)
    with open(fixture_json, 'w', encoding='utf-8') as f:
        json.dump(expected, f, ensure_ascii=False, indent=2)
    
    # 删除错误案例
    error_png.unlink()
    error_json.unlink()
    
    print(f"✅ 已提升为正式测试用例: {test_name}")
    return True


def main():
    """命令行工具"""
    import argparse
    
    parser = argparse.ArgumentParser(description="OCR 错误案例管理")
    parser.add_argument("--list", action="store_true", help="列出所有错误案例")
    parser.add_argument("--fix", type=str, help="标记错误为已修复")
    parser.add_argument("--promote", type=str, help="提升为正式测试用例")
    
    args = parser.parse_args()
    
    if args.list:
        errors = get_all_error_cases()
        if not errors:
            print("✅ 没有待修复的错误案例")
            return
        
        print(f"\n📋 待修复错误案例 ({len(errors)}个):")
        print("="*70)
        for name, info in errors:
            print(f"\n{name}:")
            print(f"  类型: {info.get('error_type', 'UNKNOWN')}")
            print(f"  详情: {info.get('error_details', '')}")
            print(f"  时间: {info.get('created_at', '')}")
            print(f"  备注: {info.get('notes', '')}")
        print()
    
    elif args.fix:
        mark_error_fixed(args.fix)
    
    elif args.promote:
        promote_error_to_fixture(args.promote)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
