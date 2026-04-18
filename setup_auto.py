#!/usr/bin/env python3
"""
Mac 微信全自动 RPA 配置向导
"""

import os
import sys
import subprocess
from pathlib import Path


def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_sip():
    """检查 SIP 状态"""
    print_header("1. 检查 SIP 状态")
    
    result = subprocess.run(['csrutil', 'status'], capture_output=True, text=True)
    
    if "enabled" in result.stdout.lower():
        print("❌ SIP 未关闭")
        print("\n请按以下步骤关闭 SIP：")
        print("  1. 重启电脑")
        print("  2. 立即按住 Cmd + R 进入恢复模式")
        print("  3. 在菜单栏选择：实用工具 → 终端")
        print("  4. 执行: csrutil disable")
        print("  5. 重启电脑")
        return False
    else:
        print("✅ SIP 已关闭")
        return True


def check_wechat():
    """检查微信"""
    print_header("2. 检查微信")
    
    result = subprocess.run(['pgrep', '-x', 'WeChat'], capture_output=True)
    
    if result.returncode == 0:
        print("✅ 微信正在运行")
        
        # 查找数据库目录
        base = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data"
        for version_dir in base.glob("Library/Application Support/com.tencent.xinWeChat/*"):
            for user_dir in version_dir.glob("*/Message"):
                if user_dir.is_dir():
                    print(f"✅ 找到数据库目录: {user_dir}")
                    return True
        
        print("⚠️  未找到数据库目录，请确认微信已登录")
        return False
    else:
        print("❌ 微信未运行")
        print("请先启动微信并登录")
        return False


def check_dependencies():
    """检查依赖"""
    print_header("3. 检查依赖")
    
    deps = ['sqlcipher', 'openssl', 'sqlite3']
    missing = []
    
    for dep in deps:
        result = subprocess.run(['which', dep], capture_output=True)
        if result.returncode != 0:
            missing.append(dep)
    
    if missing:
        print(f"❌ 缺少依赖: {', '.join(missing)}")
        print(f"\n安装命令:")
        print(f"  brew install {' '.join(missing)}")
        return False
    else:
        print("✅ 所有依赖已安装")
        return True


def setup_db_key():
    """配置数据库密钥"""
    print_header("4. 配置数据库密钥")
    
    print("获取 db_key 的方法：")
    print("  1. 使用 wechat-dump 工具")
    print("  2. 从 GitHub 搜索: wechat db key mac")
    print("  3. 查看 GET_DB_KEY.md 详细说明")
    print()
    
    db_key = input("请输入 db_key (或按回车跳过): ").strip()
    
    if db_key:
        # 写入配置文件
        config_path = Path(__file__).parent / "config" / "config.yaml"
        
        with open(config_path, 'r') as f:
            content = f.read()
        
        content = content.replace("YOUR_DB_KEY_HERE", db_key)
        
        with open(config_path, 'w') as f:
            f.write(content)
        
        print("✅ 已保存到 config/config.yaml")
        return True
    else:
        print("⚠️  未输入 db_key，稍后请手动配置")
        return False


def check_accessibility():
    """检查辅助功能权限"""
    print_header("5. 检查辅助功能权限")
    
    print("请确保终端/IDE 有辅助功能权限：")
    print("  系统设置 → 隐私与安全 → 辅助功能")
    print("  添加并勾选你的终端程序")
    print()
    
    input("配置完成后按回车继续...")
    return True


def main():
    """主流程"""
    print("""
╔══════════════════════════════════════════════════════╗
║     🤖 Mac 微信全自动 RPA 配置向导                    ║
╚══════════════════════════════════════════════════════╝
    """)
    
    checks = [
        ("SIP 状态", check_sip),
        ("微信运行", check_wechat),
        ("依赖安装", check_dependencies),
        ("数据库密钥", setup_db_key),
        ("辅助功能权限", check_accessibility),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ 检查失败: {e}")
            results.append((name, False))
    
    # 总结
    print("\n" + "=" * 60)
    print("配置总结")
    print("=" * 60)
    
    all_pass = True
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
        if not result:
            all_pass = False
    
    print("\n" + "=" * 60)
    
    if all_pass:
        print("🎉 所有检查通过！可以启动机器人了：")
        print("   ./run_auto.sh")
    else:
        print("⚠️  部分检查未通过，请修复后重试")
        print("   python3 setup_auto.py")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
