"""内置工具 - 时间、天气、搜索"""

import html
import json
import re
from datetime import datetime
from typing import Dict, Any

import requests

from .tool_registry import get_registry
from .stock_tools import stock_query


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
    """网页搜索（360 搜索，中文查询效果最佳）"""
    if not query:
        return "请提供搜索关键词"
    try:
        url = "https://www.so.com/s"
        params = {"q": query}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        text = resp.text

        results = []
        # 360 结果在 <li class="res-list"> 中
        for block in re.finditer(r'<li[^>]*class=["\']res-list["\'][^>]*>(.*?)</li>', text, re.DOTALL | re.IGNORECASE):
            block_html = block.group(1)

            # 标题
            title = ""
            hm = re.search(r'<h3[^>]*>(.*?)</h3>', block_html, re.DOTALL | re.IGNORECASE)
            if hm:
                am = re.search(r'<a[^>]*>(.*?)</a>', hm.group(1), re.DOTALL | re.IGNORECASE)
                if am:
                    title = re.sub(r'<[^>]+>', '', am.group(1)).strip()
            if not title or len(title) <= 3 or '360' in title.lower():
                continue

            # 摘要
            snippet = ""
            sm = re.search(r'<p[^>]*class=["\']res-desc["\'][^>]*>(.*?)</p>', block_html, re.DOTALL | re.IGNORECASE)
            if sm:
                snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()

            # 清理
            title = html.unescape(title)
            snippet = html.unescape(snippet)
            snippet = re.sub(r'\s+', ' ', snippet)
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."

            if snippet:
                results.append(f"{title}\n   {snippet}")
            else:
                results.append(title)

            if len(results) >= 20:
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

    registry.register(
        name="stock_query",
        description="查询股票实时行情。支持A股（sh600519/sz000001）、港股（hk00700）、美股（AAPL）。多个代码用逗号分隔。",
        parameters={
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，如 sh600519、sz000001、hk00700、AAPL。多个用逗号分隔。",
                },
            },
            "required": ["stock_code"],
        },
        func=stock_query,
    )
