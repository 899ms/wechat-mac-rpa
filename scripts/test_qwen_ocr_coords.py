#!/usr/bin/env python3
"""
测试 Qwen-VL-OCR 是否支持返回文字坐标。
如果支持，可直接替换 EasyOCR，复用现有 LayoutParser。
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

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

PROMPT_COORDS = """你是一位专业 OCR 引擎。请识别这张截图中的所有文字，并返回每个文字块的精确位置。

对每个识别到的文字块，输出以下信息：
- text: 文字内容
- x: 文字块中心点的水平坐标（0=最左，1=最右，用浮点数）
- y: 文字块中心点的垂直坐标（0=最上，1=最下，用浮点数）
- width: 文字块宽度占比（0-1，相对整图宽度）
- height: 文字块高度占比（0-1，相对整图高度）

请按从上到下、从左到右的顺序排列所有文字块。

输出格式（纯 JSON，不要 markdown）：
{
  "elements": [
    {"text": "文字1", "x": 0.12, "y": 0.05, "width": 0.08, "height": 0.02},
    {"text": "文字2", "x": 0.45, "y": 0.10, "width": 0.10, "height": 0.02}
  ]
}

注意：
- 坐标必须是 0-1 之间的浮点数
- 不要遗漏任何可见文字
- 不要输出解释，只输出 JSON
"""

PROMPT_REGION = """你是一位专业 OCR 引擎。请识别这张微信截图中的所有文字，并标注每个文字所在的 UI 区域。

微信截图分为三个区域：
1. left_panel: 左侧聊天列表（x < 0.35）
2. title_bar: 中间上方标题栏（y < 0.08, x > 0.35）
3. message_area: 中间消息区域（y > 0.08, x > 0.35）

对每个文字块输出：
- text: 文字内容
- x: 中心水平坐标（0-1）
- y: 中心垂直坐标（0-1）
- region: 所属区域（left_panel / title_bar / message_area）

输出格式（纯 JSON）：
{
  "elements": [
    {"text": "文字", "x": 0.15, "y": 0.20, "region": "left_panel"}
  ]
}
"""

PROMPT_FULL = """你正在识别一张微信 Mac 客户端截图。请提取所有文字，并标注每个文字块的位置和语义角色。

输出格式（纯 JSON）：
{
  "elements": [
    {"text": "文字内容", "x": 0.15, "y": 0.20, "type": "nickname"},
    {"text": "文字内容", "x": 0.60, "y": 0.50, "type": "message_self"},
    {"text": "文字内容", "x": 0.40, "y": 0.55, "type": "message_other"}
  ]
}

type 定义：
- nickname: 左侧聊天列表中的昵称
- unread: 红色圆形角标中的数字（极小的数字，位于头像右上角）
- preview_time: 聊天列表中的时间戳（如"09:31"、"昨天"）
- title: 中间上方标题栏文字
- message_self: 绿色气泡中的消息（屏幕右侧）
- message_other: 白色气泡中的消息（屏幕左侧）
- timestamp: 消息间的时间戳（灰色小字，如"昨天 21:58"）
- ignore: 其他无关文字（如头像内的"1000"、搜索框文字等）

坐标 x,y 均为 0-1 浮点数。
不要输出解释，只输出 JSON。
"""


def test_prompt(image_path: str, prompt: str, model: str = "qwen-vl-ocr"):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
    ]

    start = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=4096,
    )
    latency = (time.time() - start) * 1000
    raw = response.choices[0].message.content or ""

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
    except Exception as e:
        parsed = {"error": str(e), "raw": raw[:500]}

    return parsed, latency, raw


def main():
    image = PROJECT_ROOT / "tests" / "fixtures" / "regression_chat_list_pollution_20260421.png"
    if len(sys.argv) > 1:
        image = Path(sys.argv[1])

    print(f"测试图片: {image.name}")
    print(f"模型: qwen-vl-ocr")
    print()

    prompts = [
        ("坐标提取", PROMPT_COORDS),
        ("区域标注", PROMPT_REGION),
        ("完整语义", PROMPT_FULL),
    ]

    for name, prompt in prompts:
        print(f"=== {name} ===")
        parsed, latency, raw = test_prompt(str(image), prompt)
        print(f"延迟: {latency:.0f}ms")
        print(f"输出前 800 字符:\n{raw[:800]}\n")

        if "elements" in parsed:
            print(f"识别到 {len(parsed['elements'])} 个元素")
            for i, e in enumerate(parsed["elements"][:10]):
                print(f"  {i+1}. {e}")
            if len(parsed["elements"]) > 10:
                print(f"  ... 还有 {len(parsed['elements']) - 10} 个")
        print()


if __name__ == "__main__":
    main()
