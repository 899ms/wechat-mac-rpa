#!/usr/bin/env python3
"""
微信数据库密钥配置向导
"""

import os
import re
import yaml

def find_wechat_db_path():
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
                msg_path = os.path.join(version_path, user_hash, 'Message')
                if os.path.exists(msg_path):
                    # 查找数据库文件
                    for f in os.listdir(msg_path):
                        if f.startswith('msg_') and f.endswith('.db'):
                            return msg_path
    return None

def verify_db_key(db_path, db_key):
    """验证密钥是否正确"""
    import subprocess
    
    # 找一个数据库文件
    db_files = [f for f in os.listdir(db_path) if f.startswith('msg_') and f.endswith('.db')]
    if not db_files:
        return False, "未找到数据库文件"
    
    db_file = os.path.join(db_path, db_files[0])
    
    # 使用sqlcipher测试
    try:
        cmd = f"echo \"PRAGMA key = 'x\\\"{db_key}\\\"'; SELECT count(*) FROM sqlite_master;\" | sqlcipher \"{db_file}\" 2>&1"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if "ok" in result.stdout.lower() or result.returncode == 0:
            return True, "密钥验证成功"
        elif "file is not a database" in result.stderr:
            return False, "密钥错误：file is not a database"
        else:
            return False, f"验证失败: {result.stderr[:100]}"
    except Exception as e:
        return False, f"验证出错: {e}"

def main():
    print("=" * 60)
    print("       微信数据库密钥配置向导")
    print("=" * 60)
    print()
    
    # 查找数据库路径
    db_path = find_wechat_db_path()
    if db_path:
        print(f"✅ 找到微信数据库: {db_path}")
    else:
        print("⚠️  未找到微信数据库")
    print()
    
    # 显示获取密钥的方法
    print("获取 db_key 的方法:")
    print("-" * 60)
    print()
    print("方法1 - 使用 strings 命令 (推荐):")
    print("  1. 确保微信已登录并运行")
    print("  2. 打开终端，执行:")
    print("     sudo strings /Applications/WeChat.app/Contents/MacOS/WeChat | grep -E '[0-9a-f]{64}' | head -5")
    print("  3. 输入Mac密码")
    print("  4. 复制显示的 64 位十六进制字符串的前 32 位")
    print()
    print("方法2 - 使用 微信助手/小助手 等插件")
    print("  有些微信插件可以直接显示 db_key")
    print()
    print("-" * 60)
    print()
    
    # 输入密钥
    while True:
        db_key = input("请输入 db_key (32位十六进制): ").strip()
        
        # 验证格式
        if len(db_key) != 32:
            print(f"⚠️  密钥长度应为 32 位，当前 {len(db_key)} 位")
            continue
        
        if not re.match(r'^[0-9a-fA-F]{32}$', db_key):
            print("⚠️  密钥应只包含十六进制字符 (0-9, a-f)")
            continue
        
        break
    
    print()
    print(f"✅ 密钥格式正确: {db_key}")
    print()
    
    # 更新配置文件
    config_path = os.path.join(os.path.dirname(__file__), 'config/config.yaml')
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # 更新密钥
        config['wechat']['db_key'] = db_key
        
        # 如果有数据库路径，也更新
        if db_path:
            config['wechat']['db_path'] = db_path
        
        # 保存配置
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        
        print(f"✅ 配置文件已更新: {config_path}")
        print()
        
        # 尝试验证
        if db_path:
            print("正在验证密钥...")
            success, msg = verify_db_key(db_path, db_key)
            if success:
                print(f"✅ {msg}")
            else:
                print(f"⚠️  {msg}")
                print("   密钥可能不正确，请重新获取")
        
        print()
        print("=" * 60)
        print("配置完成!")
        print("=" * 60)
        print()
        print("现在可以启动机器人:")
        print("  ./run_auto.sh")
        print()
        
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")
        print()
        print("请手动编辑 config/config.yaml，修改:")
        print(f'  db_key: "{db_key}"')

if __name__ == '__main__':
    main()
