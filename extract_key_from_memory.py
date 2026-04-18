#!/usr/bin/env python3
"""
从微信进程内存中提取数据库密钥
适用于 Mac OS
"""

import subprocess
import re
import os

def get_wechat_pid():
    """获取微信主进程ID"""
    result = subprocess.run(['pgrep', '-o', 'WeChat'], capture_output=True, text=True)
    return int(result.stdout.strip()) if result.stdout.strip() else None

def get_memory_regions(pid):
    """获取进程内存区域"""
    result = subprocess.run(['vmmap', str(pid)], capture_output=True, text=True)
    regions = []
    
    for line in result.stdout.split('\n'):
        # 解析内存区域
        # 格式: 100db0000-100e54000 [ 656K 400K 0K 0K] r-x/r-x SM=COW ...
        match = re.match(r'^([0-9a-f]+)-([0-9a-f]+)\s+.*\s+([r-][w-][x-]).*', line)
        if match:
            start = int(match.group(1), 16)
            end = int(match.group(2), 16)
            perms = match.group(3)
            
            # 只查找可读的内存区域
            if 'r' in perms and end - start < 100 * 1024 * 1024:  # 限制大小
                regions.append((start, end))
    
    return regions

def search_memory_region(pid, start, end):
    """搜索内存区域中的密钥"""
    results = []
    
    try:
        # 使用 lldb 读取内存
        size = end - start
        if size > 10 * 1024 * 1024:  # 限制每次读取大小
            size = 10 * 1024 * 1024
        
        # 创建 lldb 命令
        commands = f"""
process attach --pid {pid}
memory read --force {hex(start)} -c {size}
quit
"""
        result = subprocess.run(
            ['lldb', '-b', '-s', '/dev/stdin'],
            input=commands,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # 在输出中搜索64位十六进制密钥
        pattern = r'[0-9a-f]{64}'
        matches = re.findall(pattern, result.stdout)
        
        for m in set(matches):
            results.append(m[:32])  # 取前32位
            
    except Exception as e:
        pass
    
    return results

def search_in_process_memory(pid):
    """在进程内存中搜索密钥"""
    print(f"正在分析微信进程 {pid} 的内存...")
    print("这可能需要几分钟时间...")
    print()
    
    # 获取内存区域
    regions = get_memory_regions(pid)
    print(f"找到 {len(regions)} 个内存区域")
    
    all_keys = set()
    
    # 搜索前20个区域
    for i, (start, end) in enumerate(regions[:20]):
        print(f"  搜索区域 {i+1}/20: {hex(start)}-{hex(end)}...", end='\r')
        keys = search_memory_region(pid, start, end)
        all_keys.update(keys)
        
        if len(all_keys) > 0:
            break  # 找到就停止
    
    print()
    return list(all_keys)

def main():
    print("=" * 60)
    print("       微信数据库密钥提取工具")
    print("=" * 60)
    print()
    
    # 获取微信PID
    pid = get_wechat_pid()
    if not pid:
        print("❌ 微信未运行")
        return
    
    print(f"✅ 找到微信进程 (PID: {pid})")
    print()
    
    # 搜索密钥
    keys = search_in_process_memory(pid)
    
    if keys:
        print(f"✅ 找到 {len(keys)} 个可能的密钥:")
        print()
        for i, key in enumerate(keys[:5], 1):
            print(f"  {i}. {key}")
        print()
        print("建议: 使用第一个密钥配置到 config/config.yaml")
    else:
        print("⚠️  未找到密钥")
        print()
        print("建议尝试其他方法:")
        print("  1. 安装微信小助手插件")
        print("  2. 使用微信备份工具")
        print("  3. 使用简化版机器人（不需要密钥）")

if __name__ == '__main__':
    main()
