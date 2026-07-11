#!/usr/bin/env python3
"""从 WeFlow JSON 导出中本地抽取、脱敏并分层选择本人回复样本。"""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# 本地运行时可设置 PERSONA_NAME=王芊 以匹配已有 wiki；代码里不再硬编码真名。
PERSONA_NAME = os.environ.get("PERSONA_NAME", "本人")


SENSITIVE_PATTERNS = [
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?i)https?://|www\."),
    re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b"),
    re.compile(r"(?i)wxid_[a-z0-9_]+"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    re.compile(r"验证码|密码|身份证|银行卡|收款码|付款码|转账|红包|定位|详细地址"),
]
PLACEHOLDER_PATTERNS = [
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号]"),
    (re.compile(r"(?i)https?://\S+|www\.\S+"), "[链接]"),
    (re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b"), "[邮箱]"),
    (re.compile(r"(?i)wxid_[a-z0-9_]+"), "[微信账号]"),
]
BUSINESS_WORDS = ("店长", "销售", "客服", "设计师", "中介", "物业", "团购", "商家", "客户")
FAMILY_WORDS = ("家人", "亲属", "父亲", "母亲", "爸爸", "妈妈", "夫妻", "老公", "老婆", "伴侣", "兄弟姐妹")
COLLEAGUE_WORDS = ("同事", "同学", "校友", "合作", "工作关系", "前同事")
FRIEND_WORDS = ("好友", "朋友", "关系很好", "熟识", "发小", "闺蜜")
HUMOR_PATTERNS = (
    re.compile(r"哈哈|笑死|绷不住|离谱|救命|牛的|绝了|难民|韭菜|躺平|破防|认亲"),
    re.compile(r"[😂🤣😅🤡🙃😏]|\[(?:捂脸|旺柴|破涕为笑|偷笑|呲牙)\]"),
    re.compile(r"哪有|怕不是|属实|看来.*要|估计.*正|就剩|给.*加分"),
)


@dataclass
class Candidate:
    relation: str
    chat_id: str
    context: list[str]
    replies: list[str]
    score: float
    timestamp: int
    priority: bool = False


def _stable_id(value: str, prefix: str = "chat") -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:10]}"


def _is_text(message: dict) -> bool:
    return message.get("localType") == 1 and bool(str(message.get("content") or "").strip())


def _safe_text(text: str) -> bool:
    text = text.strip()
    if not 1 <= len(text) <= 160 or text.startswith("<"):
        return False
    return not any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)


def _sanitize(text: str, names: Iterable[str]) -> str:
    result = text.strip()
    for pattern, replacement in PLACEHOLDER_PATTERNS:
        result = pattern.sub(replacement, result)
    for name in sorted({n.strip() for n in names if 2 <= len(n.strip()) <= 30}, key=len, reverse=True):
        result = result.replace(name, "[联系人]")
    return re.sub(r"\s+", " ", result).strip()


def _wiki_relation(export_path: Path, wiki_dir: Path) -> str:
    stem = export_path.stem
    if stem.startswith("群聊_"):
        return "group"
    display_name = re.sub(r"^(私聊_|曾经的好友_)", "", stem)
    safe_display_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", display_name)
    candidates = [
        wiki_dir / f"{display_name}.md",
        wiki_dir / f"{safe_display_name}.md",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore")[:5000]
            break
    persona_pattern = re.escape(PERSONA_NAME)
    match = re.search(
        r"(?ms)^##\s*与\s*(?:Bot|" + persona_pattern + r")\s*的关系\s*$\n(.*?)(?=^##\s|\Z)",
        text,
    )
    relation_text = match.group(1) if match else ""
    if any(word in relation_text for word in FAMILY_WORDS):
        return "family"
    if any(word in relation_text for word in COLLEAGUE_WORDS):
        return "colleague"
    if any(word in relation_text for word in FRIEND_WORDS):
        return "friend"
    if any(word in f"{display_name}\n{relation_text}" for word in BUSINESS_WORDS):
        return "service"
    return "acquaintance"


def _score(context: list[str], replies: list[str]) -> float:
    reply = "".join(replies)
    score = 10.0 - abs(len(reply) - 14) * 0.08
    score += min(len(context), 3) * 0.5
    score += 1.0 if re.search(r"[哈嗯哦诶吧呀呢啊嘛～~]|[？?!！]", reply) else 0.0
    score -= max(0, len(reply) - 80) * 0.08
    score -= 2.0 if re.search(r"首先|其次|综上|总之|建议您|以下是", reply) else 0.0
    score += sum(1.8 for pattern in HUMOR_PATTERNS if pattern.search(reply))
    return score


def extract_candidates(export_dir: Path, wiki_dir: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for path in sorted(export_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        messages = payload.get("messages", [])
        relation = _wiki_relation(path, wiki_dir)
        chat_id = _stable_id(path.stem)
        session_name = str(payload.get("session", {}).get("displayName") or "")
        all_names = {session_name, re.sub(r"^(私聊_|群聊_|曾经的好友_)", "", path.stem)}
        all_names.update(str(m.get("senderDisplayName") or "") for m in messages)
        i = 0
        while i < len(messages):
            if not _is_text(messages[i]) or messages[i].get("isSend"):
                i += 1
                continue
            incoming: list[dict] = []
            while i < len(messages) and _is_text(messages[i]) and not messages[i].get("isSend") and len(incoming) < 5:
                incoming.append(messages[i])
                i += 1
            outgoing: list[dict] = []
            while i < len(messages) and _is_text(messages[i]) and messages[i].get("isSend") and len(outgoing) < 3:
                outgoing.append(messages[i])
                i += 1
            if not incoming or not outgoing:
                continue
            if relation == "group":
                senders = {m.get("senderUsername") or m.get("senderDisplayName") for m in incoming}
                if len(senders) != 1:
                    continue
            raw_context = [str(m.get("content") or "") for m in incoming]
            raw_replies = [str(m.get("content") or "") for m in outgoing]
            if not all(_safe_text(t) for t in raw_context + raw_replies):
                continue
            context = [_sanitize(t, all_names) for t in raw_context]
            replies = [_sanitize(t, all_names) for t in raw_replies]
            if not all(context + replies):
                continue
            fingerprint = re.sub(r"\W+", "", "|".join(context + replies)).lower()
            if len(fingerprint) < 3 or fingerprint in seen:
                continue
            seen.add(fingerprint)
            candidates.append(Candidate(
                relation=relation,
                chat_id=chat_id,
                context=context,
                replies=replies,
                score=_score(context, replies),
                timestamp=int(outgoing[0].get("createTime") or 0),
            ))
    return candidates


def extract_chat_backup(path: Path) -> list[Candidate]:
    """抽取 GlobalStore 聊天备份；仅 sender_type=self 视为本人真实发言。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages = payload.get("messages", [])
    chat_name = str(payload.get("chat_name") or path.stem)
    chat_id = _stable_id(chat_name)
    names = {chat_name}
    names.update(str(m.get("sender") or "") for m in messages if m.get("sender_type") != "self")
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for index, message in enumerate(messages):
        if message.get("sender_type") != "self" or message.get("message_type") != "text":
            continue
        reply = str(message.get("text") or "").strip()
        if not _safe_text(reply):
            continue
        incoming: list[str] = []
        cursor = index - 1
        while cursor >= 0 and len(incoming) < 5:
            previous = messages[cursor]
            if previous.get("sender_type") == "self":
                break
            text = str(previous.get("text") or "").strip()
            if previous.get("message_type") == "text" and _safe_text(text):
                incoming.append(text)
            cursor -= 1
        if not incoming:
            continue
        context = [_sanitize(text, names) for text in reversed(incoming)]
        replies = [_sanitize(reply, names)]
        fingerprint = re.sub(r"\W+", "", "|".join(context + replies)).lower()
        if len(fingerprint) < 3 or fingerprint in seen:
            continue
        seen.add(fingerprint)
        candidates.append(Candidate(
            relation="group",
            chat_id=chat_id,
            context=context,
            replies=replies,
            score=_score(context, replies) + 6.0,
            timestamp=int(message.get("createTime") or 0),
            priority=True,
        ))
    return candidates


def select_balanced(candidates: list[Candidate], limit: int, group_target: int = 0) -> list[Candidate]:
    by_relation: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_relation[candidate.relation].append(candidate)
    for rows in by_relation.values():
        rows.sort(key=lambda c: (-c.score, -c.timestamp, c.chat_id))
    selected: list[Candidate] = []
    per_chat: Counter[str] = Counter()
    if group_target:
        group_rows = by_relation.get("group", [])
        group_rows.sort(key=lambda c: (not c.priority, -c.score, -c.timestamp, c.chat_id))
        while group_rows and len(selected) < min(group_target, limit):
            candidate = group_rows.pop(0)
            max_per_chat = 15 if candidate.priority else 3
            if per_chat[candidate.chat_id] >= max_per_chat:
                continue
            selected.append(candidate)
            per_chat[candidate.chat_id] += 1
    relations = ["family", "friend", "colleague", "acquaintance", "service"]
    if not group_target:
        relations.append("group")
    while len(selected) < limit:
        progressed = False
        for relation in relations:
            rows = by_relation.get(relation, [])
            while rows and per_chat[rows[0].chat_id] >= 3:
                rows.pop(0)
            if rows:
                candidate = rows.pop(0)
                selected.append(candidate)
                per_chat[candidate.chat_id] += 1
                progressed = True
                if len(selected) >= limit:
                    break
        if not progressed:
            break
    return selected


def write_outputs(selected: list[Candidate], output_dir: Path, candidate_count: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "persona_examples.jsonl"
    md_path = output_dir / "persona_examples.md"
    report_path = output_dir / "report.json"
    rows = []
    for index, candidate in enumerate(selected, 1):
        rows.append({
            "id": f"example_{index:03d}",
            "relationship": candidate.relation,
            "chat_id": candidate.chat_id,
            "context": candidate.context,
            "reply": candidate.replies,
        })
    jsonl_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    md_lines = ["# 本人真实回复 Few-shot（已脱敏）", "", "> 纯本地生成；请人工复核后再接入生产 prompt。", ""]
    for row in rows:
        md_lines.extend([
            f"## {row['id']} · {row['relationship']}", "",
            *[f"- 对方：{text}" for text in row["context"]],
            *[f"- 本人：{text}" for text in row["reply"]], "",
        ])
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    report = {
        "candidate_count": candidate_count,
        "selected_count": len(rows),
        "relationship_counts": dict(sorted(Counter(row["relationship"] for row in rows).items())),
        "unique_chat_count": len({row["chat_id"] for row in rows}),
        "sensitive_pattern_scan_passed": not any(
            pattern.search(text)
            for row in rows
            for text in [*row["context"], *row["reply"]]
            for pattern in SENSITIVE_PATTERNS
        ),
        "external_model_used": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/exports/b"))
    parser.add_argument("--wiki-dir", type=Path, default=Path("data/memory/wiki/users"))
    parser.add_argument("--output", type=Path, default=Path("data/few_shot"))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--group-target", type=int, default=0)
    parser.add_argument("--chat-backup", type=Path, action="append", default=[])
    args = parser.parse_args()
    candidates = extract_candidates(args.input, args.wiki_dir)
    for backup in args.chat_backup:
        candidates.extend(extract_chat_backup(backup))
    selected = select_balanced(candidates, args.limit, group_target=args.group_target)
    if len(selected) < args.limit:
        raise SystemExit(f"候选不足：需要 {args.limit}，实际 {len(selected)}")
    write_outputs(selected, args.output, len(candidates))
    print(json.dumps({"candidates": len(candidates), "selected": len(selected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
