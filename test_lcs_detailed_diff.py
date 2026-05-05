#!/usr/bin/env python3
"""详细差异分析：打印每个差异 tick 的 history 上下文 + tick 消息"""

import json
import sys
from pathlib import Path
from typing import Dict, List

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
    raw_msgs = tick_data.get("session_input_messages", [])
    if not raw_msgs:
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


def format_msg(msg: ChatMessage, chat_name: str, width: int = 50) -> str:
    sender = _normalize_sender(chat_name, msg)
    if msg.message_type in ("image", "sticker", "mixed"):
        desc = msg.image_description[:width] if msg.image_description else ""
        return f"[{sender}][{msg.message_type}] {desc}"
    else:
        text = msg.text[:width] if msg.text else ""
        return f"[{sender}][text] {text}"


def load_ticks(debug_dir: Path) -> List[dict]:
    ticks = []
    for f in sorted(debug_dir.glob("tick_*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
            d["_filename"] = f.name
            ticks.append(d)
        except Exception as e:
            pass
    ticks.sort(key=lambda x: x.get("tick_id", 0))
    return ticks


def main():
    debug_dir = Path("data/debug")
    ticks = load_ticks(debug_dir)

    chat_ticks: Dict[str, List[dict]] = {}
    for t in ticks:
        chat_name = t.get("session_input_chat_name", "") or t.get("perception_chat_name", "")
        if not chat_name:
            continue
        chat_ticks.setdefault(chat_name, []).append(t)

    for chat_name, ticks_list in chat_ticks.items():
        if chat_name != "王芊@ai开发小分队":
            continue  # 只看有差异的聊天

        store_legacy = GlobalStore(max_messages=200, state_file="data/test_legacy.json")
        store_lcs = GlobalStore(max_messages=200, state_file="data/test_lcs.json")
        store_legacy.chats = {}
        store_lcs.chats = {}

        for tick in ticks_list:
            tick_id = tick.get("tick_id", 0)
            msgs = tick_to_messages(tick, chat_name)
            if not msgs:
                continue

            for store in (store_legacy, store_lcs):
                if chat_name not in store.chats:
                    store.chats[chat_name] = type("ChatState", (), {
                        "chat_id": f"chat_{len(store.chats)}",
                        "chat_name": chat_name,
                        "messages": [],
                        "_msg_ids": set(),
                    })()

            msgs_legacy = clone_messages(msgs)
            new_legacy = store_legacy._merge_tick_legacy(chat_name, msgs_legacy)
            for msg in new_legacy:
                msg.chat_name = chat_name
                state = store_legacy.chats[chat_name]
                state.messages.append(msg)
                state._msg_ids.add(_msg_id(chat_name, msg))

            msgs_lcs = clone_messages(msgs)
            new_lcs = store_lcs._merge_tick_lcs(chat_name, msgs_lcs)
            for msg in new_lcs:
                msg.chat_name = chat_name
                state = store_lcs.chats[chat_name]
                state.messages.append(msg)
                state._msg_ids.add(_msg_id(chat_name, msg))

            legacy_ids = set(_msg_id(chat_name, m) for m in new_legacy)
            lcs_ids = set(_msg_id(chat_name, m) for m in new_lcs)

            if legacy_ids == lcs_ids:
                continue

            # 打印详细差异
            print(f"\n{'='*80}")
            print(f"TICK {tick_id} | {tick.get('_filename', '')}")
            print(f"{'='*80}")

            # 打印 history 末尾（用于对齐的窗口）
            state_lcs = store_lcs.chats[chat_name]
            search_window = min(len(state_lcs.messages) - len(new_lcs), 50)
            if search_window > 0:
                history_window = state_lcs.messages[-(search_window + len(new_lcs)):]
                if new_lcs and len(history_window) > len(new_lcs):
                    history_window = history_window[:-len(new_lcs)]
            else:
                history_window = []

            print(f"\n[History 窗口] 共 {len(history_window)} 条（tick 处理前）:")
            for i, m in enumerate(history_window):
                print(f"  H[{i:2d}] {format_msg(m, chat_name)}")

            print(f"\n[Tick 消息] 共 {len(msgs)} 条:")
            for i, m in enumerate(msgs):
                flags = []
                if _msg_id(chat_name, m) in legacy_ids:
                    flags.append("旧算法=新")
                else:
                    flags.append("旧算法=旧")
                if _msg_id(chat_name, m) in lcs_ids:
                    flags.append("新算法=新")
                else:
                    flags.append("新算法=旧")

                # 检查这条 tick 消息在 history_window 中有没有 _match_single 为 True 的
                hist_matches = []
                for hi, hm in enumerate(history_window):
                    if _match_single(hm, m, chat_name):
                        hist_matches.append(f"H[{hi}]")
                match_info = f" match={','.join(hist_matches)}" if hist_matches else " match=无"

                print(f"  T[{i:2d}] {format_msg(m, chat_name)} | {' | '.join(flags)}{match_info}")

            # LCS 详情
            if history_window:
                matched = _lcs_match(history_window, msgs, chat_name)
                print(f"\n[LCS] matched_tick_indices={sorted(matched)}, max_matched={max(matched) if matched else 'N/A'}")
                print(f"       LCS 长度={len(matched)}/{len(msgs)}")

            print(f"\n[结论]")
            print(f"  旧算法新消息: {len(new_legacy)} 条")
            print(f"  新算法新消息: {len(new_lcs)} 条")
            print(f"  旧多报: {sorted([i for i, m in enumerate(msgs) if _msg_id(chat_name, m) in legacy_ids - lcs_ids])}")
            print(f"  新多报: {sorted([i for i, m in enumerate(msgs) if _msg_id(chat_name, m) in lcs_ids - legacy_ids])}")


if __name__ == "__main__":
    main()
