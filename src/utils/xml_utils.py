#!/usr/bin/env python3
"""XML 相关的通用工具函数。"""

from typing import Optional
from xml.etree import ElementTree as ET


def _extract_xml_text(xml: str) -> Optional[str]:
    """从 XML 消息中提取可读文本（title + des）。"""
    parts = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        # 容错：如果 XML 格式不标准，尝试用根节点包裹
        try:
            root = ET.fromstring(f"<root>{xml}</root>")
        except ET.ParseError:
            return None

    for tag in ("title", "des"):
        elem = root.find(f".//{tag}")
        if elem is not None and elem.text:
            parts.append(elem.text)
    return " — ".join(parts) if parts else None
