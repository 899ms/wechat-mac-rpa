#!/usr/bin/env python3
"""XML 相关的通用工具函数。"""

import re
from typing import Optional


def _extract_xml_text(xml: str) -> Optional[str]:
    """从 XML 消息中提取可读文本（title + des）。"""
    parts = []
    title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml)
    des = re.search(r"<des>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</des>", xml)
    if title:
        parts.append(title.group(1))
    if des:
        parts.append(des.group(1))
    return " — ".join(parts) if parts else None
