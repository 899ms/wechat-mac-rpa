#!/usr/bin/env python3
"""聊天相关的通用工具函数：群聊判断、名称归一化等。

所有涉及 chat_name 的处理逻辑统一放在这里，禁止各模块自己写正则。
"""

import re
from typing import Optional


def _is_group_chat_name(chat_name: str) -> bool:
    """判断聊天名称是否为群聊（以群人数结尾，如 'ai开发小分队（128）' 或 'xxx (5)'）。"""
    if not chat_name:
        return False
    return bool(re.search(r'[（(]\d+[）)]$', chat_name))


def _normalize_chat_name(name: str) -> str:
    """对聊天名称进行 Unicode 归一化，防止 OCR 差异导致 session 分裂。

    群聊名通常以群人数结尾（如 'ai开发小分队（128）'），
    去掉后缀得到稳定的群聊标识（用于 session key）。
    """
    if not name:
        return ""
    name = name.replace("(", "（").replace(")", "）")
    name = name.replace("—", "—").replace("–", "—")
    name = name.replace(" ", "").replace("\u00a0", "").replace("\t", "")
    name = re.sub(r'^\d+[\.\、\s]*', '', name)
    # 去掉群人数后缀（如 'ai开发小分队（128）' → 'ai开发小分队'）
    name = re.sub(r'（\d+）$', '', name)
    return name.strip()


def _extract_session_key(chat_name: str) -> str:
    """从原始 chat_name 提取 session key（用于 GlobalStore 索引）。

n    等价于 _normalize_chat_name，但语义更明确。
    """
    return _normalize_chat_name(chat_name)
