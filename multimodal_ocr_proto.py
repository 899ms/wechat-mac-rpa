#!/usr/bin/env python3
"""
Multimodal OCR 原型：用 Kimi Code 多模态能力替代本地 OCR + 布局解析。

输入：微信 Mac 版截图
输出：结构化 JSON（聊天列表、消息列表、当前聊天名）
"""

import base64
import json
import sys
from pathlib import Path

from openai import OpenAI

# Kimi Code API 配置
API_KEY = "sk-kimi-Wg5YCmuwcgsNNH0Q0IFqWOyl4fbYL0OIhQgJcXghRzZ6vWkArdpj3RW3uuZGyMKD"
BASE_URL = "https://api.kimi.com/coding/v1"
MODEL = "kimi-for-coding"

# Kimi Code 需要的特殊请求头
EXTRA_HEADERS = {
    "User-Agent": "claude-code/0.1.39 (Node.js 20.11.0; darwin 23.6.0; arm64)",
    "X-Claude-Code-Version": "0.1.39",
}

PROMPT = """请仔细识别这张微信 Mac 版截图中的文字信息，并输出为 JSON。

截图包含：
1. 左侧聊天列表（昵称 + 未读角标数字）
2. 中间上方标题栏（当前聊天名称）
3. 中间消息区域（绿色气泡=自己发送，白色/灰色气泡=对方发送）

请严格按以下 JSON 格式输出（不要加 markdown 代码块，直接输出纯 JSON）：

{
  "chat_name": "当前聊天名称",
  "chat_list": [
    {"nickname": "昵称1", "unread_count": "未读数量，没有则为空字符串"},
    {"nickname": "昵称2", "unread_count": "3"}
  ],
  "messages": [
    {"sender": "自己", "text": "消息内容"},
    {"sender": "对方", "text": "消息内容"}
  ]
}

注意：
- 左侧头像区域的数字是未读角标，不要混入昵称
- 消息按从上到下顺序排列
- 绿色气泡 sender 为 "自己"，其他气泡为 "对方"
- 只输出 JSON，不要任何解释文字
"""


def image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def multimodal_ocr(image_path: str) -> dict:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, default_headers=EXTRA_HEADERS)
    b64 = image_to_base64(image_path)
    
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ],
        }
    ]
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=4000,
        )
        raw = response.choices[0].message.content or ""
        print(f"=== 模型原始输出（前1000字） ===\n{raw[:1000]}\n")
        
        # 尝试从输出中提取 JSON
        json_str = raw.strip()
        if json_str.startswith("```"):
            # 去掉 markdown 代码块
            lines = json_str.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            json_str = "\n".join(lines).strip()
        
        return json.loads(json_str)
    except Exception as e:
        return {"error": str(e), "raw": raw if 'raw' in dir() else ""}


def main():
    image_path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/regression_chat_list_pollution_20260421.png"
    
    print(f"测试图片: {image_path}")
    print(f"图片尺寸: {Path(image_path).stat().st_size / 1024:.1f} KB")
    print()
    
    result = multimodal_ocr(image_path)
    
    print("=== 解析结果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 与本地 OCR 结果对比
    print("\n=== 与本地 OCR 对比 ===")
    print("本地 OCR chat_list_nicknames: ['王老板们和小天才', 'b io 王芊 @ai开发小分队', '文件传输助手', '腾讯新闻', 'W1han', '品 王芊']")
    print("本地 OCR unread: ['', '', '', '1', '', '']")
    print("本地 OCR chat_name: '王芊 @ai开发小分队'")
    print("本地 OCR messages: 8 条")


if __name__ == "__main__":
    main()
