#!/usr/bin/env python3
"""
测试图片缩小对 qwen3-vl-plus 延迟和精度的影响。
"""

import base64
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from openai import OpenAI
except ImportError:
    print("pip install openai")
    sys.exit(1)

API_KEY = os.environ.get("DASHSCOPE_API_KEY")
if not API_KEY:
    print("export DASHSCOPE_API_KEY=sk-xxxxx")
    sys.exit(1)

client = OpenAI(api_key=API_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

PROMPT = """你正在识别一张微信 Mac 客户端截图。请提取所有文字，并标注每个文字块的位置和语义角色。

输出格式（纯 JSON）：
{
  "chat_name": "标题栏中的当前聊天名称",
  "chat_list": [
    {"nickname": "昵称", "unread_count": ""},
    {"nickname": "昵称", "unread_count": "3"}
  ],
  "messages": [
    {"sender": "自己", "text": "消息内容"},
    {"sender": "对方", "text": "消息内容"}
  ]
}

关键规则：
- 绿色气泡 = "自己"，白色/灰色气泡 = "对方"
- 未读角标是红色圆形小数字，位于头像右上角
- 头像内部的数字（如1000）不是未读角标
- 时间戳（如"昨天 21:58"）不是消息内容
- 只输出 JSON，不要解释
"""


def resize_image(image_path: str, max_size: tuple) -> Image.Image:
    """按比例缩小图片，保持长宽比。"""
    img = Image.open(image_path)
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    return img


def image_to_base64(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def call_qwen(image_b64: str, size_label: str):
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ],
        }
    ]

    start = time.time()
    try:
        response = client.chat.completions.create(
            model="qwen3-vl-plus",
            messages=messages,
            temperature=0.0,
            max_tokens=4096,
        )
        latency = (time.time() - start) * 1000
        raw = response.choices[0].message.content or ""
        usage = response.usage

        # 提取 JSON
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except:
            parsed = {"error": "parse failed", "raw": raw[:500]}

        return {
            "size_label": size_label,
            "latency_ms": latency,
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "result": parsed,
        }
    except Exception as e:
        latency = (time.time() - start) * 1000
        return {
            "size_label": size_label,
            "latency_ms": latency,
            "error": str(e),
        }


def main():
    image_path = PROJECT_ROOT / "tests" / "fixtures" / "regression_chat_list_pollution_20260421.png"
    if len(sys.argv) > 1:
        image_path = Path(sys.argv[1])

    original = Image.open(image_path)
    print(f"原图: {original.size[0]}x{original.size[1]}")
    print()

    # 测试不同尺寸
    sizes = [
        ("original", original.size),
        ("1200x1080", (1200, 1080)),
        ("900x800", (900, 800)),
        ("700x600", (700, 600)),
        ("500x450", (500, 450)),
    ]

    results = []
    for label, max_size in sizes:
        if label == "original":
            img = original.copy()
        else:
            img = resize_image(str(image_path), max_size)

        b64 = image_to_base64(img)
        print(f"测试 {label} ({img.size[0]}x{img.size[1]}) ...", end=" ", flush=True)
        result = call_qwen(b64, label)
        results.append(result)

        if "error" in result and "parse failed" not in str(result.get("error", "")):
            print(f"ERROR: {result['error']}")
        else:
            print(f"延迟: {result['latency_ms']:.0f}ms | prompt_tokens: {result.get('prompt_tokens', 'N/A')} | output_tokens: {result.get('completion_tokens', 'N/A')}")

    # 汇总
    print()
    print("=" * 80)
    print("汇总对比")
    print("=" * 80)
    print(f"{'尺寸':<15} {'延迟(ms)':<12} {'prompt_tokens':<15} {'chat_list':<50} {'messages':<10}")
    print("-" * 80)
    for r in results:
        label = r["size_label"]
        lat = f"{r['latency_ms']:.0f}"
        pt = str(r.get("prompt_tokens", "N/A"))
        res = r.get("result", {})
        chat_list = str([f"{c.get('nickname','')}:{c.get('unread_count','')}" for c in res.get("chat_list", [])])[:48]
        msgs = len(res.get("messages", []))
        print(f"{label:<15} {lat:<12} {pt:<15} {chat_list:<50} {msgs:<10}")


if __name__ == "__main__":
    main()
