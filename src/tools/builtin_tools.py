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

            # 标题和链接
            title = ""
            link = ""
            hm = re.search(r'<h3[^>]*>(.*?)</h3>', block_html, re.DOTALL | re.IGNORECASE)
            if hm:
                am = re.search(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', hm.group(1), re.DOTALL | re.IGNORECASE)
                if am:
                    link = html.unescape(am.group(1)).strip()
                    title = re.sub(r'<[^>]+>', '', am.group(2)).strip()
                    # 优先从 data-mdurl 拿真实URL（360 跳转链接是加密的，无法直接访问）
                    mdurl = re.search(r'data-mdurl=["\']([^"\']+)["\']', block_html)
                    if mdurl:
                        real = html.unescape(mdurl.group(1)).strip()
                        if real.startswith(("http://", "https://")):
                            link = real
                    else:
                        # 兜底：360 旧版跳转链接解码（url= 参数）
                        if link.startswith("https://www.so.com/link?"):
                            m = re.search(r'[?&]url=([^&]+)', link)
                            if m:
                                from urllib.parse import unquote
                                link = unquote(m.group(1))
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

            line = title
            if link:
                line += f"\n   链接：{link}"
            if snippet:
                line += f"\n   摘要：{snippet}"
            results.append(line)

            if len(results) >= 20:
                break

        if results:
            return f"搜索结果（{query}）：\n" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(results))
        return f"未找到关于'{query}'的搜索结果"
    except Exception as e:
        return f"搜索失败: {e}"


def _browse_url(url: str = "") -> str:
    """打开指定链接，提取网页正文内容。"""
    if not url:
        return "请提供要浏览的链接"
    # 补全协议头
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        html_text = resp.text

        # 1. 尝试提取 <title>
        title = ""
        tm = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.DOTALL | re.IGNORECASE)
        if tm:
            title = re.sub(r"<[^>]+>", "", tm.group(1)).strip()

        # 2. 尝试提取正文（优先 article/main/content 区域）
        body = ""
        # 微信公众号文章
        if "mp.weixin.qq.com" in url:
            m = re.search(r'<div[^>]*id=["\']js_content["\'][^>]*>(.*?)</div>\s*</div>\s*<script', html_text, re.DOTALL | re.IGNORECASE)
            if m:
                body = m.group(1)
        # 通用：article / main / [role=main]
        if not body:
            for tag in ["article", "main", 'div[^>]*role=["\']main["\']', 'div[^>]*class=["\']content["\']']:
                pat = rf'<{tag}[^>]*>(.*?)</{tag.split("[")[0].strip()}>'
                m = re.search(pat, html_text, re.DOTALL | re.IGNORECASE)
                if m and len(m.group(1)) > 200:
                    body = m.group(1)
                    break
        # 兜底：body 标签
        if not body:
            bm = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.DOTALL | re.IGNORECASE)
            if bm:
                body = bm.group(1)

        # 3. 清理 HTML 标签和脚本/style
        body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<[^>]+>", "", body)
        body = html.unescape(body)
        body = re.sub(r"\s+", " ", body).strip()

        # 4. 截断到 3000 字
        max_len = 3000
        result = body[:max_len]
        if len(body) > max_len:
            result += "..."

        preview = f"标题：{title}\n" if title else ""
        preview += f"链接：{url}\n"
        preview += f"正文：{result}"
        return preview
    except Exception as e:
        return f"浏览链接失败: {e}"


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
        name="browse_url",
        description="打开指定链接，提取网页正文内容。用户分享链接或提到 URL 时使用。",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要浏览的链接地址，如 https://example.com/article",
                },
            },
            "required": ["url"],
        },
        func=_browse_url,
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
