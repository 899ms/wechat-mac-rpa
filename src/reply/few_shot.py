"""生产回复使用的本地 persona few-shot 召回。"""

import hashlib
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any


_logger = logging.getLogger("src.reply.few_shot")


def _chat_id(chat_name: str) -> str:
    return f"chat_{hashlib.sha256(chat_name.encode('utf-8')).hexdigest()[:10]}"


def _terms(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    chars = [char for char in normalized if char.isalnum() or "\u4e00" <= char <= "\u9fff"]
    singles = chars if len(chars) <= 12 else chars[:12]
    return singles + ["".join(chars[i:i + 2]) for i in range(max(0, len(chars) - 1))]


class PersonaFewShotRetriever:
    def __init__(self, path: Path):
        self.path = path
        self._mtime_ns = -1
        self._rows: list[dict[str, Any]] = []

    def _load(self) -> list[dict[str, Any]]:
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError:
            return []
        if mtime_ns == self._mtime_ns:
            return self._rows
        rows = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("id") and isinstance(row.get("context"), list) and isinstance(row.get("reply"), list):
                    rows.append(row)
        except (OSError, json.JSONDecodeError) as exc:
            _logger.warning("persona few-shot 加载失败: %s", exc)
            return []
        self._mtime_ns = mtime_ns
        self._rows = rows
        return rows

    def retrieve(self, query: str, chat_name: str, is_group: bool, limit: int = 8) -> list[dict[str, Any]]:
        query_terms = Counter(_terms(query))
        current_chat_id = _chat_id(chat_name) if chat_name else ""
        scored = []
        for row in self._load():
            if is_group != (row.get("relationship") == "group"):
                continue
            sample_text = " ".join(row["context"] + row["reply"])
            sample_terms = Counter(_terms(sample_text))
            overlap = sum(min(count, sample_terms.get(term, 0)) for term, count in query_terms.items())
            length_similarity = 1.0 / (1.0 + abs(len(query) - len(sample_text)) / 20.0)
            same_chat = bool(current_chat_id and row.get("chat_id") == current_chat_id)
            scored.append((same_chat, overlap * 2.0 + length_similarity, row["id"], row))
        scored.sort(key=lambda item: (not item[0], -item[1], item[2]))
        return [row for _, _, _, row in scored[:max(0, limit)]]

    @staticmethod
    def render(rows: list[dict[str, Any]], max_chars: int = 2500) -> tuple[str, list[str]]:
        if not rows:
            return "", []
        parts = [
            "【本人真实聊天风格示例】",
            "以下内容只用于模仿表达长度、语气、接梗方式和聊天节奏。",
            "示例中的人物、事件和事实都不是当前对话事实，禁止照搬或引用。",
        ]
        ids = []
        for row in rows:
            block = [f"示例 {row['id']}："]
            block.extend(f"对方：{text}" for text in row["context"])
            block.extend(f"本人：{text}" for text in row["reply"])
            if len("\n".join(parts + block)) > max_chars:
                break
            parts.extend(block)
            ids.append(row["id"])
        return ("\n".join(parts), ids) if ids else ("", [])
