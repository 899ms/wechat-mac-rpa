#!/usr/bin/env python3
"""从历史聊天记录初始化 LLM Wiki（含关系推理）。"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def is_group_chat(chat_name: str) -> bool:
    return (
        ("(" in chat_name and ")" in chat_name)
        or ("（" in chat_name and "）" in chat_name)
        or chat_name.endswith("群")
        or "群聊" in chat_name
        or "@" in chat_name
    )


def is_valid_sender(sender: str, chat_name: str, is_group: bool) -> bool:
    if not sender or sender in ("对方", "[未知]", ""):
        return False
    if is_group and sender == chat_name:
        return False
    return True


def load_global_state(path: str = "data/global_state.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"加载全局状态失败: {e}")
        return {}


# ── 个人 wiki Prompt ──
_USER_PROMPT = """请根据以下对话记录，为这位用户写一篇 wiki 简介。

【对话记录】
{conversation}

【输出格式】
# {user_name}

## 基本信息
（城市、职业、年龄等，有就写，没有写"暂不了解"）

## 偏好 & 兴趣
（喜欢什么、讨厌什么、关注什么话题）

## 近期动态
（最近聊过的话题、计划、问过的问题，带日期）

## 社交关系（从对话中推断）
（别人怎么称呼TA、TA和群里其他人的关系、绰号/外号）

## 交互风格
（说话方式、和 Bot 的关系）

规则：
1. 只写确定的信息，不确定的写"暂不了解"
2. 不要编造
3. 特别关注"别人怎么称呼TA"（如@时的称呼、绰号、外号）
4. 控制长度，不超过 800 字
5. 直接输出 markdown，不要加代码块标记
"""


# ── 群聊 wiki Prompt ──
_GROUP_PROMPT = """请根据以下群聊记录，为这个群写一篇 wiki。

【群聊记录】
{conversation}

【输出格式】
# {group_name}

## 群基本信息
（群类型、氛围、主要话题方向）

## 活跃成员
（列出常说话的人，以及推断出的角色/绰号/关系）

## 成员关系推理
- 谁和谁是朋友/同事/家人？
- 群里有什么绰号、外号、梗？
- 谁经常@谁？谁经常接谁的话？

## 近期话题
（最近讨论过什么）

## 群默契/梗
（只有群里人才懂的内梗）

规则：
1. 关系推断要有依据，不确定的写"推测"
2. 不要编造不存在的关系
3. 控制长度，不超过 1000 字
4. 直接输出 markdown，不要加代码块标记
"""


def format_conversation(msgs, max_msgs=40):
    msgs = sorted(msgs, key=lambda x: x[1] or "")
    msgs = msgs[-max_msgs:]
    lines = []
    for chat_name, ts, sender, text in msgs:
        time_tag = f"[{ts}] " if ts else ""
        loc_tag = f"（{chat_name}）" if is_group_chat(chat_name) else ""
        lines.append(f"{time_tag}{sender}{loc_tag}：{text}")
    return "\n".join(lines)


def call_llm(prompt, llm_client, max_tokens=1500):
    try:
        response = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        wiki = response if isinstance(response, str) else getattr(response, "content", str(response))
        wiki = wiki.strip()
        return wiki if len(wiki) > 50 else ""
    except Exception as e:
        print(f"    LLM 错误: {e}")
        return ""


def extract_user_conversations(state: dict):
    user_msgs = defaultdict(list)
    for chat_name, chat_state in state.items():
        messages = chat_state.get("messages", [])
        is_group = is_group_chat(chat_name)
        for msg in messages:
            sender = msg.get("sender", "")
            sender_type = msg.get("sender_type", "")
            text = msg.get("text", "")
            reply_time = msg.get("reply_time")
            if not text or sender_type == "self":
                continue
            ts_str = ""
            if reply_time:
                try:
                    ts_str = datetime.fromtimestamp(reply_time).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
            if not is_group:
                user_name = chat_name
            else:
                if not is_valid_sender(sender, chat_name, is_group):
                    continue
                user_name = sender
            user_msgs[user_name].append((chat_name, ts_str, sender, text))
    return user_msgs


def extract_group_conversations(state: dict):
    """提取每个群聊的对话记录。"""
    groups = {}
    for chat_name, chat_state in state.items():
        if not is_group_chat(chat_name):
            continue
        messages = chat_state.get("messages", [])
        msgs = []
        for msg in messages:
            sender = msg.get("sender", "")
            sender_type = msg.get("sender_type", "")
            text = msg.get("text", "")
            reply_time = msg.get("reply_time")
            if not text:
                continue
            ts_str = ""
            if reply_time:
                try:
                    ts_str = datetime.fromtimestamp(reply_time).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
            msgs.append((chat_name, ts_str, sender or "[未知]", text))
        if msgs:
            groups[chat_name] = msgs
    return groups


def main():
    print("=" * 50)
    print("从历史聊天记录初始化 LLM Wiki（含关系推理）")
    print("=" * 50)

    state = load_global_state()
    if not state:
        print("没有历史记录，退出")
        return

    try:
        from utils.qwen_client import QwenClient
        llm_client = QwenClient(model="deepseek-v4-flash")
        print("LLM 客户端初始化成功\n")
    except Exception as e:
        print(f"LLM 客户端初始化失败: {e}")
        return

    users_dir = Path("data/memory/wiki/users")
    groups_dir = Path("data/memory/wiki/groups")
    users_dir.mkdir(parents=True, exist_ok=True)
    groups_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧文件
    for old in users_dir.glob("*.md"):
        old.unlink()
    for old in groups_dir.glob("*.md"):
        old.unlink()

    # ── 1. 生成个人 wiki ──
    user_msgs = extract_user_conversations(state)
    print(f"发现 {len(user_msgs)} 个用户，开始生成个人 wiki…\n")
    user_success = 0
    for user_name, msgs in sorted(user_msgs.items()):
        if len(msgs) < 3:
            continue
        print(f"  用户: {user_name}（{len(msgs)} 条消息）")
        conversation = format_conversation(msgs)
        prompt = _USER_PROMPT.format(user_name=user_name, conversation=conversation)
        wiki = call_llm(prompt, llm_client, max_tokens=1500)
        if wiki:
            (users_dir / f"{user_name}.md").write_text(wiki, encoding="utf-8")
            user_success += 1
            print(f"    ✓ 已生成")
        else:
            print(f"    ✗ 跳过")

    # ── 2. 生成群聊 wiki（含关系推理） ──
    group_msgs = extract_group_conversations(state)
    print(f"\n发现 {len(group_msgs)} 个群聊，开始生成群 wiki…\n")
    group_success = 0
    for group_name, msgs in sorted(group_msgs.items()):
        if len(msgs) < 5:
            continue
        print(f"  群聊: {group_name}（{len(msgs)} 条消息）")
        conversation = format_conversation(msgs, max_msgs=50)
        prompt = _GROUP_PROMPT.format(group_name=group_name, conversation=conversation)
        wiki = call_llm(prompt, llm_client, max_tokens=2000)
        if wiki:
            (groups_dir / f"{group_name}.md").write_text(wiki, encoding="utf-8")
            group_success += 1
            print(f"    ✓ 已生成")
        else:
            print(f"    ✗ 跳过")

    print(f"\n{'=' * 50}")
    print(f"完成！个人 wiki: {user_success}，群聊 wiki: {group_success}")
    print(f"目录: {users_dir} / {groups_dir}")


if __name__ == "__main__":
    main()
