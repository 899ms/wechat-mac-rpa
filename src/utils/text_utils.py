#!/usr/bin/env python3
"""文本处理通用工具函数。"""


def _truncate_text(text: str, max_len: int, suffix: str = "\n\n... [truncated]") -> str:
    """截断文本到指定长度，保留尾部提示。"""
    if not text or len(text) <= max_len:
        return text
    return text[:max_len] + suffix


def _compress_text(text: str, max_chars: int) -> str:
    """压缩长文本：优先保留开头和结尾，中间用省略号连接。"""
    if not text or len(text) <= max_chars:
        return text
    # 保留头 40% + 尾 60%
    head_len = int(max_chars * 0.4)
    tail_len = int(max_chars * 0.6)
    return text[:head_len] + "\n...（中间省略）...\n" + text[-tail_len:]
