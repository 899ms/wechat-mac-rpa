#!/usr/bin/env python3
"""
批量生成群聊 wiki (v4) - 第一轮：所有群最近 500 条消息生成基础 wiki
- 并发 4 个，外层 600s 强制超时
- 断点续传（跳过已有 wiki 文件）
- 保存到 data/memory/wiki/groups/
"""

import sys
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.session.global_store import GlobalStore
from src.utils.qwen_client import QwenClient

_logger = logging.getLogger(__name__)

client = QwenClient(model="deepseek-v4-flash")
wiki_dir = Path("data/memory/wiki/groups")
wiki_dir.mkdir(parents=True, exist_ok=True)

store = GlobalStore()

_DEFAULT_GROUP_WIKI = """# {group_name}

## 群基本信息
（暂无）

## 群成员画像
（暂无）

## 近期话题 & 动态
（暂无）

## 群内规则 & 文化
（暂无）
"""

_UPDATE_GROUP_PROMPT = """请根据以下对话记录，生成/更新群聊 wiki。

【现有 wiki】
{current_wiki}

【新对话】
群聊：{chat_name}
时间：{current_time}

对话内容：
{conversation}

【更新规则】
1. 只修改/新增变化的部分，保留未变动的内容
2. 标注日期：时间敏感的信息必须带日期（格式：YYYY-MM-DD）
3. 过期处理：超过 7 天的"近期动态"移到历史记录或删除
4. 冲突处理：新信息覆盖旧信息
5. 重点记录：
   - 群成员关系、身份、职业变化
   - 群内热点话题、事件、约定
   - 群内文化、梗、常用语
   - 群规则、禁忌、注意事项
6. 多账号标注：如果对话来源包含不同账号标记（如 [work]、[personal]），在 wiki 中标注该信息所属账号
7. 不确定的信息用 [待验证] 标记
8. **区分陈述和疑问/玩笑/反问（严格）**：以下句子严禁当作事实提取：
   - 以"吗"、"呢"、"?"、"？"结尾的句子
   - 反问句（如"不是你说我...的吗"）
   - 开玩笑/夸张表述（如"富比有多少资产"）
   - 用户考问Bot的问题（如"王乔元是谁"）
   这些属于交互行为，不是事实，严禁写入 wiki。
9. 控制长度：群聊 wiki 不超过 2000 字
10. 保持 Markdown 格式

【输出】
直接输出更新后的完整 wiki markdown，不要加代码块标记。"""


def safe_filename(name: str) -> str:
    """生成安全文件名（保留中文）"""
    return "".join(c if c.isalnum() or c in "_-\u4e00-\u9fff" else "_" for c in name)


def format_conversation(messages):
    lines = []
    for m in messages:
        sender = getattr(m, 'sender', '?')
        text = getattr(m, 'text', '')
        ts_int = getattr(m, 'create_time', None)
        tstr = ""
        if ts_int:
            try:
                tstr = datetime.fromtimestamp(int(ts_int)).strftime("%Y-%m-%d %H:%M")
            except Exception as e:
                _logger.warning("timestamp conversion failed: %s", e)
        lines.append(f"[{tstr}] {sender}: {text}")
    return "\n".join(lines)


def process_chat(name_state):
    name, state = name_state
    safe = safe_filename(name)
    wiki_path = wiki_dir / f"{safe}.md"

    # 断点续传：已有 wiki 且长度 >100 则跳过
    if wiki_path.exists() and wiki_path.stat().st_size > 100:
        return name, "exists"

    msg_count = len(state.messages)
    if msg_count == 0:
        return name, "empty"

    # 第一轮：取最近 500 条
    limit = min(msg_count, 500)
    recent = state.messages[-limit:]
    conversation = format_conversation(recent)

    current_wiki = _DEFAULT_GROUP_WIKI.format(group_name=name)
    if wiki_path.exists():
        current_wiki = wiki_path.read_text(encoding="utf-8")

    now = time.strftime("%Y-%m-%d %H:%M")
    prompt = _UPDATE_GROUP_PROMPT.format(
        current_wiki=current_wiki,
        chat_name=name,
        current_time=now,
        conversation=conversation,
    )

    try:
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
            timeout=500,
        )
        new_wiki = response.strip() if response else ""
        if new_wiki and len(new_wiki) > 50:
            wiki_path.write_text(new_wiki, encoding="utf-8")
            return name, f"ok_{len(new_wiki)}"
        return name, "short"
    except Exception as e:
        return name, f"error_{e}"


# 准备任务
chats = list(store.chats.items())
total = len(chats)
print(f"总共 {total} 个聊天，第一轮：最近 500 条生成基础 wiki（并发 4，timeout 500s）...")

success = 0
failed = 0
skipped = 0

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(process_chat, item): item[0] for item in chats}
    for i, future in enumerate(as_completed(futures), 1):
        name = futures[future]
        try:
            _, status = future.result(timeout=600)
        except Exception as e:
            status = f"timeout_{e}"

        if status.startswith("ok"):
            success += 1
        elif status == "exists":
            skipped += 1
        else:
            failed += 1

        if i % 20 == 0 or i <= 5 or status.startswith("error") or status.startswith("timeout"):
            print(f"  [{i}/{total}] {name[:40]}... {status} | 成功:{success} 跳过:{skipped} 失败:{failed}")

print(f"\n第一轮完成: 成功={success} 跳过={skipped} 失败={failed}")
