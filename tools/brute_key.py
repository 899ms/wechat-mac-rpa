#!/usr/bin/env python3
"""
尝试从微信进程中获取数据库密钥
"""

import subprocess
import re
import os

def get_wechat_pid():
    """获取微信进程ID"""
    try:
        result = subprocess.run(['pgrep', 'WeChat'], capture_output=True, text=True)
        pids = result.stdout.strip().split('\n')
        return int(pids[0]) if pids[0] else None
    except:
        return None

def get_db_path():
    """查找微信数据库路径"""
    home = os.path.expanduser('~')
    base_path = os.path.join(home, 'Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat')
    
    if not os.path.exists(base_path):
        return None
    
    # 查找版本目录
    for version in os.listdir(base_path):
        version_path = os.path.join(base_path, version)
        if os.path.isdir(version_path):
            # 查找用户目录
            for user_hash in os.listdir(version_path):
                user_path = os.path.join(version_path, user_hash, 'Message')
                if os.path.exists(user_path):
                    # 查找数据库文件
                    for f in os.listdir(user_path):
                        if f.startswith('msg_') and f.endswith('.db'):
                            return os.path.join(user_path, f)
    return None

def try_strings_method():
    """尝试使用strings命令获取密钥"""
    print("尝试使用 strings 命令获取密钥...")
    print("提示: 这可能需要 sudo 权限")
    print()
    
    try:
        # 尝试不使用sudo
        result = subprocess.run(
            ['strings', '/Applications/WeChat.app/Contents/MacOS/WeChat'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # 查找64位十六进制字符串 (可能是db_key的两倍长度)
        pattern = r'[0-9a-f]{64}'
        matches = re.findall(pattern, result.stdout)
        
        if matches:
            print(f"✅ 找到 {len(matches)} 个可能的密钥:")
            print()
            for i, match in enumerate(matches[:5], 1):
                db_key = match[:32]  # 取前32位
                print(f"  {i}. 完整: {match}")
                print(f"     db_key: {db_key}")
                print()
            return matches[0][:32]
        else:
            print("⚠️  未找到匹配的密钥")
            return None
            
    except subprocess.TimeoutExpired:
        print("⚠️  命令超时")
        return None
    except Exception as e:
        print(f"⚠️  错误: {e}")
        return None

def main():
    print("=" * 60)
    print("       微信数据库密钥获取工具")
    print("=" * 60)
    print()
    
    # 检查微信是否运行
    pid = get_wechat_pid()
    if not pid:
        print("⚠️  微信未运行，请先启动微信")
        input("按回车键退出...")
        return
    
    print(f"✅ 微信正在运行 (PID: {pid})")
    print()
    
    # 查找数据库
    db_path = get_db_path()
    if db_path:
        print(f"✅ 找到数据库: {db_path}")
        print()
    
    # 尝试获取密钥
    db_key = try_strings_method()
    
    if db_key:
        print("=" * 60)
        print(f"🎯 建议使用的 db_key: {db_key}")
        print("=" * 60)
        print()
        print("下一步:")
        print(f"  1. 编辑配置文件: nano ~/wechat-mac-rpa/config/config.yaml")
        print(f"  2. 修改 db_key: \"{db_key}\"")
        print(f"  3. 运行: ~/wechat-mac-rpa/run_auto.sh")
    else:
        print()
        print("⚠️  自动获取失败，请尝试以下方法:")
        print()
        print("方法A - 使用 sudo strings:")
        print("  sudo strings /Applications/WeChat.app/Contents/MacOS/WeChat | grep -E '[0-9a-f]{{64}}' | head -5")
        print()
        print("方法B - 手动复制数据库到解密工具:")
        print(f"  数据库位置: {db_path or '自动查找失败，请手动查找'}")
        
    print()
    input("按回车键退出...")

if __name__ == '__main__':
    main()
