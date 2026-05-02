#!/usr/bin/env python3
"""
测试 Qwen-VL-OCR 返回坐标的精度和一致性。
目标：验证是否能替换 EasyOCR，复用现有 LayoutParser。
"""

import base64
import json
import os
import sys
import time
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

# 精简 prompt：只要求文字 + 归一化坐标，不做语义分类（分类交给现有代码）
PROMPT_BBOX = """请识别这张截图中的所有文字，并返回每个文字块的归一化坐标。

要求：
1. 坐标必须是 0-1 之间的浮点数（相对整图宽高的比例）
2. 返回每个文字块的：中心点 x、中心点 y、宽度占比 w、高度占比 h
3. 不要合并相邻文字，每个独立文字块单独输出
4. 不要遗漏任何可见文字，包括小数字（如角标"3"、时间"09:31"）
5. 头像内部的装饰数字（如"10"、"100"、"1000"）也要输出

输出格式（纯 JSON，不要 markdown）：
{
  "elements": [
    {"text": "文字", "x": 0.15, "y": 0.20, "w": 0.08, "h": 0.02}
  ]
}
"""

# 带语义分类的 prompt，但要求统一坐标格式
PROMPT_SEMANTIC = """请识别这张微信截图中的所有文字，标注归一化坐标和语义类型。

坐标规则（必须严格遵守）：
- x, y：文字块中心点，0-1 浮点数（相对整图宽高的比例）
- w, h：文字块宽高占比，0-1 浮点数

类型规则：
- nickname: 左侧聊天列表中的用户/群名称
- preview: 聊天列表中的消息预览文字
- time: 聊天列表右侧的时间戳（如"09:31"、"昨天"）
- unread: 头像右上角的红色圆形角标数字（通常只有1-2位，面积很小）
- title: 中间上方标题栏文字
- message: 中间消息区域的对话文字
- timestamp: 消息之间的时间戳（灰色小字，如"昨天 21:58"）
- other: 其他无关文字（搜索框、头像内数字等）

注意：
- 聊天列表中，昵称和预览消息、时间戳要分成不同元素
- 未读角标通常非常小，位于头像右上角

输出格式（纯 JSON）：
{
  "elements": [
    {"text": "文字", "x": 0.15, "y": 0.20, "w": 0.08, "h": 0.02, "type": "nickname"}
  ]
}
"""


def call_api(image_path: str, prompt: str, model: str = "qwen-vl-ocr"):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    start = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        temperature=0.0,
        max_tokens=4096,
    )
    latency = (time.time() - start) * 1000
    raw = response.choices[0].message.content or ""

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


def visualize_elements(image_path: str, elements: list, output_path: str):
    """把识别到的元素画在图上，验证坐标准确性。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    w, h = img.size

    colors = {
        "nickname": "#00FF00",
        "preview": "#00AA00",
        "time": "#AAAA00",
        "unread": "#FF0000",
        "title": "#0000FF",
        "message": "#FF00FF",
        "timestamp": "#888888",
        "other": "#CCCCCC",
    }

    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 14)
    except:
        font = ImageFont.load_default()

    for i, e in enumerate(elements):
        x = e.get("x", 0)
        y = e.get("y", 0)
        ew = e.get("w", 0.05)
        eh = e.get("h", 0.02)
        tp = e.get("type", "other")

        # 处理列表类型的坐标（如 [198, 92, 19, 129, 90]）
        if isinstance(x, list):
            # 尝试解析 [x, y, w, h, angle] 或 [x1, y1, x2, y2, ...]
            if len(x) >= 4:
                # 假设是 [center_x, center_y, width, height, angle]
                px, py = int(x[0]), int(x[1])
                pw, ph = int(x[2]), int(x[3])
            else:
                px, py = int(x[0]), int(y) if not isinstance(y, list) else int(y[0])
                pw, ph = int(ew) if not isinstance(ew, list) else int(ew[0]), int(eh) if not isinstance(eh, list) else int(eh[0])
        elif isinstance(x, (int, float)) and isinstance(y, (int, float)):
            # 支持归一化坐标和像素坐标
            if x <= 1.0 and y <= 1.0 and (isinstance(ew, (int, float)) and ew <= 1.0):
                px, py = int(x * w), int(y * h)
                pw, ph = int(ew * w), int(eh * h)
            else:
                px, py = int(x), int(y)
                pw, ph = int(ew), int(eh)
        else:
            continue

        color = colors.get(tp, "#FFFFFF")
        draw.rectangle([px - pw//2, py - ph//2, px + pw//2, py + ph//2], outline=color, width=2)
        draw.text((px - pw//2, py - ph//2 - 16), f"{i+1}:{e.get('text', '')[:10]}", fill=color, font=font)

    img.save(output_path)
    print(f"可视化已保存: {output_path}")


def main():
    image = PROJECT_ROOT / "tests" / "fixtures" / "regression_chat_list_pollution_20260421.png"
    if len(sys.argv) > 1:
        image = Path(sys.argv[1])

    img = Image.open(image)
    print(f"图片: {image.name} ({img.size[0]}x{img.size[1]})")
    print(f"模型: qwen-vl-ocr")
    print()

    # 测试 bbox prompt
    print("=== Prompt: 纯坐标 ===")
    parsed, latency, raw = call_api(str(image), PROMPT_BBOX)
    print(f"延迟: {latency:.0f}ms | 输出长度: {len(raw)} chars")
    elements = parsed.get("elements", [])
    print(f"识别到 {len(elements)} 个元素")
    for e in elements[:15]:
        print(f"  {e}")
    if len(elements) > 15:
        print(f"  ... 还有 {len(elements) - 15} 个")

    if elements:
        vis_path = PROJECT_ROOT / "results" / "qwen_ocr_bbox_viz.png"
        vis_path.parent.mkdir(parents=True, exist_ok=True)
        visualize_elements(str(image), elements, str(vis_path))
    print()

    # 测试语义 prompt
    print("=== Prompt: 语义分类 ===")
    parsed2, latency2, raw2 = call_api(str(image), PROMPT_SEMANTIC)
    print(f"延迟: {latency2:.0f}ms | 输出长度: {len(raw2)} chars")
    elements2 = parsed2.get("elements", [])
    print(f"识别到 {len(elements2)} 个元素")

    # 按类型统计
    from collections import Counter
    types = Counter(e.get("type", "unknown") for e in elements2)
    print(f"类型分布: {dict(types)}")

    for e in elements2[:15]:
        print(f"  {e}")
    if len(elements2) > 15:
        print(f"  ... 还有 {len(elements2) - 15} 个")

    if elements2:
        vis_path2 = PROJECT_ROOT / "results" / "qwen_ocr_semantic_viz.png"
        visualize_elements(str(image), elements2, str(vis_path2))


if __name__ == "__main__":
    main()
