"""内置工具 - 时间、天气、搜索"""

import json
from datetime import datetime
from typing import Dict, Any

import requests

from .tool_registry import get_registry


def _get_current_time() -> str:
    """获取当前时间"""
    now = datetime.now()
    return now.strftime("%Y年%m月%d日 %H:%M:%S %A")


def _get_weather(city: str = "", date: str = "今天") -> str:
    """获取指定城市的天气"""
    if not city:
        return "请提供城市名称"
    try:
        # 使用 wttr.in 免费天气 API
        url = f"https://wttr.in/{city}?format=j1&lang=zh"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        current = data["current_condition"][0]
        temp = current["temp_C"]
        desc = current["lang_zh"][0]["value"] if "lang_zh" in current else current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        wind = current["windspeedKmph"]
        return f"{city} {date}：{desc}，{temp}℃，湿度{humidity}%，风速{wind}km/h"
    except Exception as e:
        return f"获取{city}天气失败: {e}"


def _web_search(query: str = "") -> str:
    """网页搜索"""
    if not query:
        return "请提供搜索关键词"
    try:
        # 使用 DuckDuckGo HTML 搜索
        url = "https://duckduckgo.com/html/"
        params = {"q": query, "kl": "zh-cn"}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        # 简单提取搜索结果标题和摘要
        import re
        results = []
        # 匹配结果标题和摘要
        for m in re.finditer(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', resp.text):
            title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if title and len(title) > 5:
                results.append(title)
            if len(results) >= 5:
                break
        if results:
            return f"搜索结果（{query}）：\n" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(results))
        return f"未找到关于'{query}'的搜索结果"
    except Exception as e:
        return f"搜索失败: {e}"


def register_builtin_tools():
    """注册所有内置工具"""
    registry = get_registry()

    registry.register(
        name="get_current_time",
        description="获取当前日期和时间",
        parameters={
            "type": "object",
            "properties": {},
        },
        func=_get_current_time,
    )

    registry.register(
        name="get_weather",
        description="获取指定城市的天气信息。日期可选，默认为今天。",
        parameters={
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，如'上海'、'北京'、'东京'",
                },
                "date": {
                    "type": "string",
                    "description": "日期，如'今天'、'明天'、'后天'，默认为今天",
                },
            },
            "required": ["city"],
        },
        func=_get_weather,
    )

    registry.register(
        name="web_search",
        description="在网页上搜索信息，获取实时新闻、知识、数据等",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
            },
            "required": ["query"],
        },
        func=_web_search,
    )
