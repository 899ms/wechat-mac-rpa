#!/usr/bin/env python3
"""A/B 对比测试：LCS 新算法 vs 滑动前缀旧算法"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from wechat_rpa.models.base import ChatMessage, SenderType
from wechat_rpa.session.global_store import (
    GlobalStore,
    _lcs_match,
    _match_single,
    _msg_id,
    _is_fuzzy_duplicate,
    _normalize_sender,
)


def tick_to_messages(tick_data: dict, chat_name: str) -> List[ChatMessage]:
    """把 tick 中的 session_input_messages 转成 ChatMessage 列表"""
    raw_msgs = tick_data.get("session_input_messages", [])
    if not raw_msgs:
        # 兜底：从 api_response 取
        api_resp = tick_data.get("api_response", {})
        if isinstance(api_resp, str):
            try:
                api_resp = json.loads(api_resp)
            except (json.JSONDecodeError, TypeError):
                api_resp = {}
        if isinstance(api_resp, dict):
            raw_msgs = api_resp.get("messages", [])

    msgs = []
    for m in raw_msgs:
        sender_type_str = m.get("sender_type", "other")
        try:
            sender_type = SenderType(sender_type_str)
        except ValueError:
            sender_type = SenderType.OTHER

        msg = ChatMessage(
            text=m.get("text", ""),
            sender=m.get("sender", ""),
            sender_type=sender_type,
            chat_name=chat_name,
            message_type=m.get("type", "text"),
            image_description=m.get("image_desc", m.get("image_description", "")),
            image_text=m.get("image_text", ""),
            is_image_duplicate=m.get("image_dup", False),
        )
        msgs.append(msg)
    return msgs


def clone_messages(msgs: List[ChatMessage]) -> List[ChatMessage]:
    """深拷贝消息列表（用于 A/B 测试的独立副本）"""
    return [
        ChatMessage(
            text=m.text,
            sender=m.sender,
            sender_type=m.sender_type,
            chat_name=m.chat_name,
            is_at_me=m.is_at_me,
            message_type=m.message_type,
            image_description=m.image_description,
            image_text=m.image_text,
            is_image_duplicate=m.is_image_duplicate,
        )
        for m in msgs
    ]


def load_ticks(debug_dir: Path) -> List[dict]:
    """加载并按时间排序所有 tick 文件"""
    ticks = []
    for f in sorted(debug_dir.glob("tick_*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
            d["_filename"] = f.name
            ticks.append(d)
        except Exception as e:
            print(f"跳过 {f.name}: {e}")
    # 按 tick_id 排序（时间顺序）
    ticks.sort(key=lambda x: x.get("tick_id", 0))
    return ticks


def format_msg_summary(msg: ChatMessage, chat_name: str) -> str:
    """单条消息摘要"""
    sender = _normalize_sender(chat_name, msg)
    if msg.message_type in ("image", "sticker", "mixed"):
        desc = msg.image_description[:40] if msg.image_description else ""
        return f"[{sender}][{msg.message_type}] {desc}"
    else:
        text = msg.text[:40] if msg.text else ""
        return f"[{sender}][text] {text}"


def main():
    debug_dir = Path("data/debug")
    ticks = load_ticks(debug_dir)
    print(f"加载了 {len(ticks)} 个 tick 文件\n")

    # 按 chat_name 分组（因为不同聊天的历史是独立的）
    chat_ticks: Dict[str, List[dict]] = {}
    for t in ticks:
        chat_name = t.get("session_input_chat_name", "") or t.get("perception_chat_name", "")
        if not chat_name:
            continue
        chat_ticks.setdefault(chat_name, []).append(t)

    print(f"涉及 {len(chat_ticks)} 个聊天:\n")
    for chat_name in chat_ticks:
        print(f"  - {chat_name}: {len(chat_ticks[chat_name])} ticks")

    total_diffs = 0

    for chat_name, ticks_list in chat_ticks.items():
        print(f"\n{'='*60}")
        print(f"聊天: {chat_name}")
        print(f"{'='*60}")

        # 两个独立的 store，分别运行旧算法和新算法
        store_legacy = GlobalStore(max_messages=200, state_file="data/test_legacy.json")
        store_lcs = GlobalStore(max_messages=200, state_file="data/test_lcs.json")

        # 清空（避免之前测试的残留）
        store_legacy.chats = {}
        store_lcs.chats = {}

        chat_diffs = 0

        for tick in ticks_list:
            tick_id = tick.get("tick_id", 0)
            filename = tick.get("_filename", "")
            msgs = tick_to_messages(tick, chat_name)

            if not msgs:
                continue

            # 确保 state 存在
            for store in (store_legacy, store_lcs):
                if chat_name not in store.chats:
                    store.chats[chat_name] = type("ChatState", (), {
                        "chat_id": f"chat_{len(store.chats)}",
                        "chat_name": chat_name,
                        "messages": [],
                        "_msg_ids": set(),
                    })()

            # 旧算法
            msgs_legacy = clone_messages(msgs)
            new_legacy = store_legacy._merge_tick_legacy(chat_name, msgs_legacy)
            # 手动添加到历史（因为 _merge_tick_legacy 只返回新消息，不修改 state）
            for msg in new_legacy:
                msg.chat_name = chat_name
                state = store_legacy.chats[chat_name]
                state.messages.append(msg)
                state._msg_ids.add(_msg_id(chat_name, msg))

            # 新算法
            msgs_lcs = clone_messages(msgs)
            new_lcs = store_lcs._merge_tick_lcs(chat_name, msgs_lcs)
            for msg in new_lcs:
                msg.chat_name = chat_name
                state = store_lcs.chats[chat_name]
                state.messages.append(msg)
                state._msg_ids.add(_msg_id(chat_name, msg))

            # 对比结果
            legacy_ids = [_msg_id(chat_name, m) for m in new_legacy]
            lcs_ids = [_msg_id(chat_name, m) for m in new_lcs]

            if set(legacy_ids) != set(lcs_ids):
                chat_diffs += 1
                print(f"\n--- tick {tick_id} ({filename}) ---")
                print(f"tick 消息 ({len(msgs)}条):")
                for i, m in enumerate(msgs):
                    marker = ""
                    print(f"  [{i}] {format_msg_summary(m, chat_name)}{marker}")

                print(f"\n旧算法识别为新消息 ({len(new_legacy)}条):")
                for m in new_legacy:
                    print(f"  ✓ {format_msg_summary(m, chat_name)}")

                print(f"\n新算法识别为新消息 ({len(new_lcs)}条):")
                for m in new_lcs:
                    print(f"  ✓ {format_msg_summary(m, chat_name)}")

                # 打印 LCS 匹配详情
                if store_lcs.chats.get(chat_name) and len(store_lcs.chats[chat_name].messages) > len(msgs):
                    search_window = min(len(store_lcs.chats[chat_name].messages) - len(new_lcs), 50)
                    history_window = store_lcs.chats[chat_name].messages[-(search_window + len(new_lcs)):]
                    if len(history_window) > len(new_lcs):
                        history_window = history_window[:-len(new_lcs)] if new_lcs else history_window
                    matched = _lcs_match(history_window, msgs_lcs, chat_name)
                    if matched:
                        print(f"\nLCS 匹配详情: matched={sorted(matched)}, max_matched={max(matched)}")

        if chat_diffs == 0:
            print("  ✅ 新旧算法结果完全一致")
        else:
            print(f"\n  ⚠️  共 {chat_diffs}/{len(ticks_list)} 个 tick 存在差异")

        total_diffs += chat_diffs

    print(f"\n{'='*60}")
    print(f"总计: {total_diffs} 个 tick 存在差异")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
