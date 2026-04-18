#!/usr/bin/env python3
"""
测试常见密钥
"""
import os
import subprocess

# 常见密钥列表
common_keys = [
    "00000000000000000000000000000000",
    "1234567890abcdef1234567890abcdef",
    "deadbeefdeadbeefdeadbeefdeadbeef",
    "abcdef1234567890abcdef1234567890",
    "0123456789abcdef0123456789abcdef",
    "fedcba9876543210fedcba9876543210",
    "aabbccddeeff00112233445566778899",
    "00112233445566778899aabbccddeeff",
    "11223344556677889900aabbccddeeff",
    "ffffffffffffffffffffffffffffffff",
]

# 找到数据库文件
home = os.path.expanduser('~')
base_path = os.path.join(home, 'Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat/2.0b4.0.9')
db_file = None

for user_hash in os.listdir(base_path):
    msg_path = os.path.join(base_path, user_hash, 'Message', 'msg_0.db')
    if os.path.exists(msg_path):
        db_file = msg_path
        break

if not db_file:
    print("❌ 未找到数据库文件")
    exit(1)

print(f"📁 数据库: {db_file}")
print(f"🔑 正在测试 {len(common_keys)} 个常见密钥...")
print()

# 测试每个密钥
for key in common_keys:
    print(f"  测试: {key}", end='\r')
    try:
        # 使用 sqlcipher 测试
        test_cmd = f"PRAGMA key = \"x'{key}'\"; SELECT count(*) FROM sqlite_master;"
        cmd = ['sqlcipher', db_file]
        result = subprocess.run(
            cmd, 
            input=test_cmd, 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        output = result.stdout + result.stderr
        if "error" not in output.lower() and "ok" in output.lower():
            print(f"\n✅ 找到正确密钥: {key}")
            print(f"   请将此密钥配置到 config/config.yaml")
            break
    except Exception as e:
        pass

print()
print("如果以上密钥都不正确，请尝试其他方法获取 db_key")
