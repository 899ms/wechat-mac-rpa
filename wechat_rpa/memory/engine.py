#!/usr/bin/env python3
"""Memory Engine - LLM Wiki based long-term memory with overrides support."""

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional


# 默认 wiki 模板
_DEFAULT_USER_WIKI = """# {user_name}

## 基本信息
（暂无）

## 偏好 & 兴趣
（暂无）

## 近期动态
（暂无）

## 说过的话（短期）
（暂无）

## 交互风格
（暂无）
"""

_UPDATE_PROMPT = """请根据以下对话记录，更新用户 wiki。

【现有 wiki】
{current_wiki}

【新对话】
聊天：{chat_name}
时间：{current_time}

对话内容：
{conversation}

【更新规则】
1. 只修改/新增变化的部分，保留未变动的内容
2. 标注日期：时间敏感的信息必须带日期（格式：YYYY-MM-DD）
3. 过期处理：超过 7 天的"近期动态"移到"说过的话"或删除
4. 冲突处理：新信息覆盖旧信息
5. 不确定的信息用 [待验证] 标记
6. 控制长度：个人 wiki 不超过 1500 字
7. 保持 Markdown 格式

【输出】
直接输出更新后的完整 wiki markdown，不要加代码块标记。"""


class MemoryEngine:
    """LLM Wiki 记忆引擎：管理用户/群聊/话题的 wiki 文件，支持外挂 overrides。"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.wiki_dir = Path("data/memory/wiki")
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        (self.wiki_dir / "users").mkdir(exist_ok=True)
        (self.wiki_dir / "groups").mkdir(exist_ok=True)
        (self.wiki_dir / "topics").mkdir(exist_ok=True)

        # 外挂配置
        self.overrides_dir = Path("data/memory/overrides")
        self.overrides_dir.mkdir(parents=True, exist_ok=True)
        self._aliases: Dict[str, List[str]] = {}      # 用户名 -> [别名列表]
        self._facts: Dict[str, List[dict]] = {}       # 用户名 -> [事实列表]
        self._corrections: Dict[str, List[str]] = {}  # 群名 -> [纠正列表]
        self._load_overrides()

        # 异步更新队列
        self._update_queue: List[dict] = []
        self._queue_lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown = False
        self._start_worker()

    # ── Overrides 加载 ──

    def _load_overrides(self) -> None:
        """加载外挂配置（aliases / facts / corrections）。"""
        # aliases
        aliases_path = self.overrides_dir / "aliases.json"
        if aliases_path.exists():
            try:
                data = json.loads(aliases_path.read_text(encoding="utf-8"))
                for user, cfg in data.get("users", {}).items():
                    self._aliases[user] = cfg.get("aliases", [])
            except Exception:
                pass

        # facts
        facts_path = self.overrides_dir / "facts.json"
        if facts_path.exists():
            try:
                data = json.loads(facts_path.read_text(encoding="utf-8"))
                for user, cfg in data.get("users", {}).items():
                    self._facts[user] = cfg.get("facts", [])
            except Exception:
                pass

        # corrections
        corrections_path = self.overrides_dir / "corrections.json"
        if corrections_path.exists():
            try:
                data = json.loads(corrections_path.read_text(encoding="utf-8"))
                for group, cfg in data.get("groups", {}).items():
                    self._corrections[group] = cfg.get("corrections", [])
            except Exception:
                pass

    def _resolve_alias(self, user_name: str) -> str:
        """根据别名找到主用户名。"""
        for main_name, aliases in self._aliases.items():
            if user_name == main_name or user_name in aliases:
                return main_name
        return user_name

    def _all_names_for(self, user_name: str) -> List[str]:
        """获取一个用户的所有名字（主名 + 别名）。"""
        resolved = self._resolve_alias(user_name)
        names = [resolved]
        names.extend(self._aliases.get(resolved, []))
        return list(dict.fromkeys(names))  # 去重保序

    # ── 读取接口 ──

    def get_user_memory(self, user_name: str, max_chars: int = 2000) -> str:
        """读取用户 wiki（含别名合并 + 外挂 facts），返回压缩后的摘要。facts 放在前面确保不被截断。"""
        resolved = self._resolve_alias(user_name)
        all_names = self._all_names_for(resolved)

        # 合并所有别名的 wiki
        wikis = []
        for name in all_names:
            path = self.wiki_dir / "users" / f"{name}.md"
            if path.exists():
                wikis.append(self._load_wiki(path))

        # 先构建 facts（放在前面，确保截断时不丢失）
        facts = self._facts.get(resolved, [])
        facts_text = ""
        if facts:
            fact_lines = ["## 补充信息（人工标注）"]
            for f in facts:
                fact_lines.append(f"- {f.get('relation', '')}：{f.get('value', '')}")
                if f.get("note"):
                    fact_lines.append(f"  （{f['note']}）")
            facts_text = "\n".join(fact_lines)

        if not wikis and not facts_text:
            return ""

        # facts 放在 wiki 前面，确保即使截断也保留人工标注
        wiki_text = "\n\n".join(wikis)
        if facts_text and wiki_text:
            wiki_text = facts_text + "\n\n" + wiki_text
        elif facts_text:
            wiki_text = facts_text

        return self._compress_wiki(wiki_text, max_chars)

    def get_group_memory(self, group_name: str, max_chars: int = 2000) -> str:
        """读取群聊 wiki（含外挂 corrections），返回压缩后的摘要。"""
        path = self.wiki_dir / "groups" / f"{group_name}.md"
        wiki = self._load_wiki(path) if path.exists() else ""

        # 注入纠正信息
        corrections = self._corrections.get(group_name, [])
        if corrections:
            corr_text = "\n\n## 重要纠正（人工标注）\n" + "\n".join(f"- {c}" for c in corrections)
            if wiki:
                wiki = wiki + "\n" + corr_text
            else:
                wiki = corr_text

        if not wiki:
            return ""
        return self._compress_wiki(wiki, max_chars)

    # ── 更新接口 ──

    def update_user_wiki(self, user_name: str, chat_name: str,
                         messages: List, bot_replies: List[str]) -> None:
        """把更新任务加入队列，后台异步执行。"""
        if not user_name or self.llm_client is None:
            return
        resolved = self._resolve_alias(user_name)
        with self._queue_lock:
            self._update_queue.append({
                "type": "user",
                "user_name": resolved,  # 用主用户名更新
                "chat_name": chat_name,
                "messages": messages,
                "bot_replies": bot_replies,
                "timestamp": time.time(),
            })

    def update_group_wiki(self, group_name: str, messages, bot_replies) -> None:
        """更新群聊 wiki。（Phase 2 实现）"""
        pass

    def shutdown(self) -> None:
        """关闭 worker 线程，等待队列清空。"""
        self._shutdown = True
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

    # ── 内部方法 ──

    def _user_wiki_path(self, user_name: str) -> Path:
        return self.wiki_dir / "users" / f"{user_name}.md"

    def _load_wiki(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _save_wiki(self, path: Path, content: str) -> None:
        try:
            path.write_text(content, encoding="utf-8")
        except Exception:
            pass

    def _compress_wiki(self, wiki: str, max_chars: int) -> str:
        """压缩 wiki 到指定长度。"""
        wiki = wiki.strip()
        if len(wiki) <= max_chars:
            return wiki
        truncated = wiki[:max_chars]
        last_break = max(truncated.rfind("\n## "), truncated.rfind("\n- "), truncated.rfind("\n\n"))
        if last_break > max_chars * 0.5:
            truncated = truncated[:last_break]
        return truncated.strip() + "\n（…记忆已截断）"

    def _format_conversation(self, messages: List, bot_replies: List[str]) -> str:
        lines = []
        for msg in messages:
            sender = "我" if getattr(msg, "sender_type", None) and msg.sender_type.value == "self" else getattr(msg, "sender", "")
            lines.append(f"{sender}：{getattr(msg, 'text', '')}")
        if bot_replies:
            for reply in bot_replies:
                lines.append(f"Bot：{reply}")
        return "\n".join(lines)

    def _do_update(self, task: dict) -> None:
        """执行单次 wiki 更新。"""
        user_name = task["user_name"]
        chat_name = task["chat_name"]
        messages = task["messages"]
        bot_replies = task["bot_replies"]

        path = self._user_wiki_path(user_name)
        current_wiki = self._load_wiki(path) if path.exists() else _DEFAULT_USER_WIKI.format(user_name=user_name)

        conversation = self._format_conversation(messages, bot_replies)
        if not conversation.strip():
            return

        now = time.strftime("%Y-%m-%d %H:%M")
        prompt = _UPDATE_PROMPT.format(
            current_wiki=current_wiki,
            chat_name=chat_name,
            current_time=now,
            conversation=conversation,
        )

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            new_wiki = response if isinstance(response, str) else getattr(response, "content", str(response))
            new_wiki = new_wiki.strip()
            if new_wiki and len(new_wiki) > 50:
                self._save_wiki(path, new_wiki)
        except Exception:
            pass

    def _expand_search_keywords(self, keyword: str) -> List[str]:
        """把关键词扩展为包含主名和所有别名的搜索词列表。"""
        keywords = {keyword}
        resolved = self._resolve_alias(keyword)
        keywords.add(resolved)
        # 找到该用户对应的所有别名（双向：主名→别名，别名→主名）
        for main_name, aliases in self._aliases.items():
            if resolved == main_name or keyword == main_name:
                keywords.update(aliases)
                keywords.add(main_name)
            elif keyword in aliases or resolved in aliases:
                keywords.update(aliases)
                keywords.add(main_name)
        return list(keywords)

    def _extract_all_snippets(self, content: str, keywords: List[str], max_snippets: int = 2) -> List[str]:
        """从内容中提取所有包含关键词的片段，去重，限制数量。"""
        snippets = []
        seen_ranges = set()  # 避免重叠片段
        for kw in keywords:
            start = 0
            while True:
                idx = content.find(kw, start)
                if idx < 0:
                    break
                # 检查是否与已有片段重叠（±50字范围内视为重叠）
                overlap = False
                for (s, e) in seen_ranges:
                    if abs(idx - s) < 50 or abs(idx - e) < 50:
                        overlap = True
                        break
                if not overlap:
                    snippet_start = max(0, idx - 80)
                    snippet_end = min(len(content), idx + 150)
                    snippet = content[snippet_start:snippet_end].strip()
                    if snippet_start > 0:
                        snippet = "…" + snippet
                    if snippet_end < len(content):
                        snippet = snippet + "…"
                    snippets.append(snippet)
                    seen_ranges.add((snippet_start, snippet_end))
                start = idx + len(kw)
                if len(snippets) >= max_snippets:
                    break
            if len(snippets) >= max_snippets:
                break
        return snippets

    def search_keyword(self, keyword: str, max_chars: int = 2000) -> str:
        """在所有 wiki 中搜索关键词，返回相关片段。包含 facts/corrections/aliases。
        支持空格分隔的多个关键词分别搜索。提取所有匹配片段，确保不遗漏。"""
        if not keyword or len(keyword.strip()) < 2:
            return ""
        # 按空格分词，分别搜索每个关键词（去掉太短的词）
        raw_keywords = [kw.strip() for kw in keyword.split() if len(kw.strip()) >= 2]
        if not raw_keywords:
            raw_keywords = [keyword.strip()]
        # 扩展每个关键词的别名
        keywords = []
        for kw in raw_keywords:
            keywords.extend(self._expand_search_keywords(kw))
        # 去重
        keywords = list(dict.fromkeys(keywords))

        # 优先返回被搜索关键词解析到的用户
        resolved_keyword = self._resolve_alias(raw_keywords[0] if raw_keywords else keyword.strip())

        primary_results = []   # 关键词对应的主用户
        other_results = []     # 其他匹配用户
        seen_users = set()

        # 搜索个人 wiki（wiki + facts 合并后统一搜索，提取所有匹配片段）
        for path in (self.wiki_dir / "users").glob("*.md"):
            user = path.stem
            resolved_user = self._resolve_alias(user)
            if resolved_user in seen_users:
                continue

            wiki_content = self._load_wiki(path)
            # 构建 facts 文本
            facts = self._facts.get(resolved_user, [])
            facts_text = ""
            if facts:
                facts_text = "\n".join([
                    "## 补充信息（人工标注）",
                    *[f"- {f.get('relation', '')}：{f.get('value', '')}" + (f"\n  （{f['note']}）" if f.get("note") else "") for f in facts]
                ])
            # 合并内容（facts + wiki）用于搜索
            full_content = facts_text + "\n\n" + wiki_content if facts_text and wiki_content else (facts_text or wiki_content)
            if not full_content:
                continue

            # 检查是否匹配任何关键词
            matched = any(kw in full_content for kw in keywords)
            if matched:
                seen_users.add(resolved_user)
                snippets = self._extract_all_snippets(full_content, keywords, max_snippets=2)
                target = primary_results if resolved_user == resolved_keyword else other_results
                for snippet in snippets:
                    target.append(f"【{resolved_user}的记忆】{snippet}")

        # 搜索群聊 wiki（wiki + corrections 合并后统一搜索）
        for path in (self.wiki_dir / "groups").glob("*.md"):
            group = path.stem
            wiki_content = self._load_wiki(path)
            corrections = self._corrections.get(group, [])
            corr_text = ""
            if corrections:
                corr_text = "## 重要纠正（人工标注）\n" + "\n".join(f"- {c}" for c in corrections)
            full_content = corr_text + "\n\n" + wiki_content if corr_text and wiki_content else (corr_text or wiki_content)
            if not full_content:
                continue

            matched = any(kw in full_content for kw in keywords)
            if matched:
                snippets = self._extract_all_snippets(full_content, keywords, max_snippets=2)
                for snippet in snippets:
                    other_results.append(f"【{group}群记忆】{snippet}")

        results = primary_results + other_results
        if not results:
            return f"未在本地记忆中找到关于'{keyword}'的信息"

        # 合并结果，控制在 max_chars 内（保留完整片段，不截断到片段中间）
        text = "\n".join(results)
        if len(text) <= max_chars:
            return text
        truncated = ""
        for snippet in results:
            if len(truncated) + len(snippet) + 1 > max_chars:
                truncated += "\n（…更多结果省略）"
                break
            truncated = truncated + "\n" + snippet if truncated else snippet
        return truncated

    def _start_worker(self) -> None:
        """启动后台 worker 线程，定期处理更新队列。"""
        def _worker():
            while not self._shutdown:
                time.sleep(5)
                batch = []
                with self._queue_lock:
                    if len(self._update_queue) >= 3:
                        batch = self._update_queue[:3]
                        self._update_queue = self._update_queue[3:]
                    elif self._update_queue:
                        now = time.time()
                        cutoff = [i for i, t in enumerate(self._update_queue) if now - t["timestamp"] > 300]
                        if cutoff:
                            batch = self._update_queue[:cutoff[-1] + 1]
                            self._update_queue = self._update_queue[len(batch):]
                for task in batch:
                    self._do_update(task)
                    time.sleep(1)

        self._worker_thread = threading.Thread(target=_worker, daemon=True)
        self._worker_thread.start()
