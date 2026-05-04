#!/usr/bin/env python3
"""L4 Reply Generator - 回复内容生成."""

import time
from typing import Any, Dict, List

from wechat_rpa.models.base import ChatMessage, SenderType
from wechat_rpa.session.chat_session import ChatSession
from wechat_rpa.tools import get_registry, register_builtin_tools
from wechat_rpa.reply.session_memory import SessionMemory, _extract_query_key


class ReplyGenerator:
    def __init__(self, llm_client=None, complex_llm_client=None, memory_engine=None):
        self.llm_client = llm_client
        self.complex_llm_client = complex_llm_client
        self.memory_engine = memory_engine
        print(f"[Hermes] ReplyGenerator init: llm_client={type(llm_client).__name__ if llm_client else None}, complex_llm_client={type(complex_llm_client).__name__ if complex_llm_client else None}")
        # 最后一次调用的 prompt/response（供 debug 使用）
        self.last_system_prompt: str = ""
        self.last_tools_context: str = ""
        self.last_user_prompt: str = ""
        self.last_raw_response: str = ""
        # 多轮调用完整链路（供 debug 使用）
        self.last_llm_calls: List[Dict] = []
        self.last_tool_calls: List[Dict] = []
        self.last_generation_trace: List[Dict] = []
        # Skill 加载状态（供 debug 使用）
        self.last_loaded_skills: List[str] = []
        self.last_skill_injected_content: str = ""
        # Hermes 联调专用 debug 字段
        self.last_active_llm: str = ""
        self.last_hermes_fallback_triggered: bool = False
        self.last_hermes_messages: List[Dict] = []
        self.last_hermes_response: str = ""
        # 注册内置工具
        self.tool_registry = get_registry()
        register_builtin_tools()
        # 短期记忆（跨 tick 缓存工具结果）
        self.session_memory = SessionMemory()
        # 动态注册记忆搜索工具（如果 memory_engine 可用）
        if self.memory_engine is not None:
            def _search_memory_adapter(query: str = "") -> str:
                """适配器：工具参数名 query → 引擎参数名 keyword"""
                return self.memory_engine.search_keyword(query)

            self.tool_registry.register(
                name="search_memory",
                description="搜索本地长期记忆。当你不确定某个人是谁、某件事的背景、或者某个关系时，调用此工具查询本地 wiki 记忆库。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词。必须是单个具体的人名、昵称或名词，不要组合多个词，不要包含'关系''称呼''是谁''什么'等泛词。正确示例：'王海'、'小海哥'、'王璇'。错误示例：'王璇 王海 关系 称呼'",
                        },
                    },
                    "required": ["query"],
                },
                func=_search_memory_adapter,
            )

    def generate(self, unreplied: List[ChatMessage], all_messages: List[ChatMessage]) -> List[str]:
        """
        生成回复内容，返回多条回复列表（最多3条）。
        支持多轮工具调用，但总工具时间不超过 max_tool_seconds，超时后强制生成文本回复。
        """
        if not unreplied:
            return []

        fallback_msg = unreplied[-1]

        if self.llm_client is None:
            return []

        # 重置 debug 状态
        self.last_system_prompt = ""
        self.last_tools_context = ""
        self.last_user_prompt = ""
        self.last_raw_response = ""
        self.last_llm_calls = []
        self.last_tool_calls = []
        self.last_generation_trace = []
        self.last_loaded_skills = []
        self.last_skill_injected_content = ""
        self.last_hermes_fallback_triggered = False
        self.last_hermes_messages = []
        self.last_hermes_response = ""

        chat_name = unreplied[-1].chat_name if unreplied else ""
        system_prompt = self._system_prompt()
        tools_context = self._build_tools_context(chat_name)
        user_prompt = self._build_user_prompt(unreplied, all_messages)

        # 模型辅助路由：按需加载匹配的 skill 正文到 user prompt
        last_msg = unreplied[-1]
        route_text = last_msg.text or last_msg.image_description or ""
        matched_skills = self._route_skills(route_text)
        self.last_loaded_skills = matched_skills

        # 模型选择：加载了 skill 的复杂任务优先走 complex_llm_client（hermes）
        active_llm = self.llm_client
        active_llm_name = "deepseek"
        is_hermes = False
        if matched_skills and self.complex_llm_client is not None:
            active_llm = self.complex_llm_client
            active_llm_name = "hermes"
            is_hermes = True
            print(f"[Hermes] matched_skills={matched_skills} → 切换 active_llm=hermes，让 Hermes 自己加载 skill")
        else:
            has_hermes = self.complex_llm_client is not None
            print(f"[Hermes] matched_skills={matched_skills}, complex_llm_available={has_hermes} → active_llm=deepseek")
        self.last_active_llm = active_llm_name

        # Skill 注入：只有 deepseek 才注入 Bot 的 skill，Hermes 用自己的 skill
        skill_parts = []
        if matched_skills and not is_hermes:
            for skill_name in matched_skills:
                content = self._load_skill_content(skill_name)
                if content:
                    skill_parts.append(f"【{skill_name} 技能指南】\n{content}")
            if skill_parts:
                user_prompt += "\n\n" + "\n\n".join(skill_parts)
        self.last_skill_injected_content = "\n\n".join(skill_parts) if skill_parts else ""

        self.last_system_prompt = system_prompt
        self.last_tools_context = tools_context
        self.last_user_prompt = user_prompt

        tools = self.tool_registry.to_openai_schemas()

        llm_calls: List[Dict] = []
        tool_calls: List[Dict] = []
        trace: List[Dict] = []

        max_retries = 2
        max_tool_seconds = 20.0  # 工具调用阶段最多 20 秒
        max_total_seconds = 600.0 if is_hermes else 35.0  # Hermes 给足 10 分钟
        overall_start_time = time.time()

        # 构建 messages：system（人设）+ system（工具缓存）+ user（上下文）
        messages = [{"role": "system", "content": system_prompt}]
        if tools_context:
            messages.append({"role": "system", "content": tools_context})
        messages.append({"role": "user", "content": user_prompt})

        # Hermes 走精简 system prompt，不传 tools
        if is_hermes:
            messages[0]["content"] = self._hermes_system_prompt()
            print(f"[Hermes] 使用精简 system prompt，不传 tools")
        tool_round_count = 0  # 已执行的 tool 轮数
        max_tool_rounds = 10  # 最多允许 10 轮 tool 调用（如先 stock_query 再 web_search）

        for attempt in range(max_retries + 1):
            start_time = time.time()

            try:
                while True:
                    elapsed = time.time() - start_time
                    total_elapsed = time.time() - overall_start_time
                    force_no_tools = elapsed > max_tool_seconds

                    # 总时间兜底
                    if total_elapsed > max_total_seconds:
                        force_no_tools = True

                    # 调用 LLM（matched_skills 时走 active_llm=hermes）
                    actual_tools = None if (force_no_tools or is_hermes) else (tools if tools else None)
                    llm_timeout = 600 if is_hermes else 30
                    raw = active_llm.chat(messages=messages, tools=actual_tools, max_tokens=2000, timeout=llm_timeout)
                    raw_content = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
                    raw_tool_calls = getattr(raw, "tool_calls", None)

                    # 记录 LLM 调用（summary）
                    llm_calls.append({
                        "attempt": attempt + 1,
                        "elapsed": round(elapsed, 2),
                        "messages_count": len(messages),
                        "has_tools": bool(actual_tools),
                        "has_tool_calls": bool(raw_tool_calls),
                        "response_preview": raw_content[:500] if raw_content else "",
                    })

                    # 记录完整 trace（请求）
                    trace.append({
                        "round": len(trace) // 3 + 1,
                        "type": "llm_request",
                        "timestamp": time.time(),
                        "attempt": attempt + 1,
                        "messages": self._truncate_messages(messages),
                        "tools": actual_tools,
                        "force_no_tools": force_no_tools,
                    })

                    # 记录完整 trace（响应）
                    trace.append({
                        "round": len(trace) // 3 + 1,
                        "type": "llm_response",
                        "timestamp": time.time(),
                        "content": raw_content[:2000] if raw_content else "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                            for tc in (raw_tool_calls or [])
                        ],
                    })

                    # 工具调用处理
                    if raw_tool_calls and not force_no_tools:
                        assistant_msg = {
                            "role": "assistant",
                            "content": raw.content or "",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in raw_tool_calls
                            ],
                        }
                        messages.append(assistant_msg)

                        for tc in raw_tool_calls:
                            tool_name = tc.function.name
                            tool_args = tc.function.arguments
                            if self.tool_registry.has(tool_name):
                                result = self.tool_registry.get(tool_name).execute(tool_args)
                            else:
                                result = f"工具 {tool_name} 不存在"

                            # 保存到 session memory（跨 tick 缓存）
                            try:
                                query_key = _extract_query_key(tool_name, tool_args)
                                self.session_memory.add_tool_result(chat_name, tool_name, query_key, str(result)[:1000])
                            except Exception:
                                pass

                            # 记录工具调用（summary）
                            tool_calls.append({
                                "attempt": attempt + 1,
                                "tool_call_id": tc.id,
                                "tool_name": tool_name,
                                "arguments": tool_args,
                                "result_preview": str(result)[:500] if result else "",
                            })

                            # 记录完整 trace（工具执行）
                            trace.append({
                                "round": len(trace) // 3 + 1,
                                "type": "tool_execution",
                                "timestamp": time.time(),
                                "tool_call_id": tc.id,
                                "tool_name": tool_name,
                                "arguments": tool_args,
                                "result": str(result)[:2000] if result else "",
                            })

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result,
                            })

                        # 完成一轮 tool 调用
                        tool_round_count += 1
                        continue

                    # 文本回复（或强制无 tools 后的回复）
                    text = raw_content
                    self.last_raw_response = text
                    replies = self._parse_replies(text)
                    if replies:
                        model_name = "hermes" if active_llm is self.complex_llm_client else "deepseek"
                        print(f"[Hermes] {model_name} 直接生成 replies={len(replies)} 条")
                        # 直接走 Hermes 时也记录 hermes debug 字段
                        if active_llm is self.complex_llm_client:
                            self.last_hermes_messages = [dict(m) for m in messages]
                            self.last_hermes_response = text or ""
                        for r in replies:
                            self.session_memory.add_reply(chat_name, r)
                        self.last_llm_calls = llm_calls
                        self.last_tool_calls = tool_calls
                        self.last_generation_trace.extend(trace)
                        return replies

                    # deepseek 请求切换 hermes → 保留 tool 结果上下文，只换 system prompt
                    if text and '"use_hermes"' in text and self.complex_llm_client is not None:
                        print(f"[Hermes] deepseek 输出 use_hermes → 切 Hermes 重新生成")
                        self.last_hermes_fallback_triggered = True
                        # 基于当前 messages（含 tool 调用结果），替换 system prompt
                        hermes_system = self._hermes_system_prompt()
                        hermes_messages = [dict(m) for m in messages]
                        if hermes_messages and hermes_messages[0].get("role") == "system":
                            hermes_messages[0]["content"] = hermes_system
                        else:
                            hermes_messages.insert(0, {"role": "system", "content": hermes_system})

                        self.last_generation_trace.append({
                            "round": len(trace) // 3 + 1,
                            "type": "hermes_fallback_request",
                            "timestamp": time.time(),
                            "note": "deepseek 判定需复杂推理，切 hermes 重新生成",
                            "messages_count": len(hermes_messages),
                        })
                        print(f"[Hermes] 请求: messages={len(hermes_messages)} 条, 含 tool={any(m.get('role')=='tool' for m in hermes_messages)}")
                        hermes_raw = self.complex_llm_client.chat(messages=hermes_messages, tools=None, max_tokens=2000)
                        hermes_text = hermes_raw if isinstance(hermes_raw, str) else getattr(hermes_raw, "content", str(hermes_raw))
                        print(f"[Hermes] 响应预览: {hermes_text[:100] if hermes_text else '(空)'}...")
                        self.last_hermes_messages = hermes_messages
                        self.last_hermes_response = hermes_text or ""
                        self.last_generation_trace.append({
                            "round": len(trace) // 3 + 1,
                            "type": "hermes_fallback_response",
                            "timestamp": time.time(),
                            "content": hermes_text[:2000] if hermes_text else "",
                        })
                        hermes_replies = self._parse_replies(hermes_text)
                        if hermes_replies:
                            print(f"[Hermes] 生成 replies={len(hermes_replies)} 条")
                            for r in hermes_replies:
                                self.session_memory.add_reply(chat_name, r)
                            self.last_llm_calls = llm_calls
                            self.last_tool_calls = tool_calls
                            self.last_raw_response = hermes_text
                            self.last_generation_trace.extend(trace)
                            return hermes_replies
                        # hermes 也返回空 → fallback 到不回复
                        print(f"[Hermes] 返回空 replies")
                        self.last_llm_calls = llm_calls
                        self.last_tool_calls = tool_calls
                        self.last_generation_trace.extend(trace)
                        return []

                    # LLM 明确输出了 {"replies": []} → 正确决策（不想回复），不 retry
                    if text and '"replies"' in text:
                        print(f"[Hermes] LLM 输出空 replies → 正确决策不回复")
                        self.last_llm_calls = llm_calls
                        self.last_tool_calls = tool_calls
                        self.last_generation_trace.extend(trace)
                        return []

                    # 空回复处理（LLM 返回空字符串或无效内容）
                    if force_no_tools:
                        # 已经禁用了 tools，再 retry 也无法获取新信息，直接不回复
                        print(f"[Hermes] force_no_tools 空回复 → 不回复")
                        self.last_raw_response = f"[空回复且已禁用tools，attempt={attempt+1}]"
                        self.last_llm_calls = llm_calls
                        self.last_tool_calls = tool_calls
                        self.last_generation_trace.extend(trace)
                        return []

                    self.last_raw_response = f"[空回复，attempt={attempt+1}]"
                    break  # 跳出 while，进入下一次 retry

            except Exception as e:
                self.last_raw_response = f"[ERROR attempt={attempt+1}: {type(e).__name__}: {e}]"
                llm_calls.append({
                    "attempt": attempt + 1,
                    "error": f"{type(e).__name__}: {e}",
                })
                trace.append({
                    "type": "error",
                    "timestamp": time.time(),
                    "attempt": attempt + 1,
                    "error": f"{type(e).__name__}: {e}",
                })
                if attempt < max_retries:
                    time.sleep(1)

        print(f"[Hermes] generate 最终返回空 ( exhausted retries )")
        self.last_llm_calls = llm_calls
        self.last_tool_calls = tool_calls
        self.last_generation_trace.extend(trace)

        return []

    def _truncate_messages(self, messages: List[Dict]) -> List[Dict]:
        """截断 messages 内容，防止 debug JSON 过大。"""
        truncated = []
        for m in messages:
            cm = dict(m)
            if "content" in cm and isinstance(cm["content"], str) and len(cm["content"]) > 1000:
                cm["content"] = cm["content"][:1000] + "... [truncated]"
            if "tool_calls" in cm:
                cm["tool_calls"] = [{"id": tc.get("id"), "name": tc.get("function", {}).get("name")} for tc in cm["tool_calls"]]
            truncated.append(cm)
        return truncated

    def _parse_replies(self, text: str) -> List[str]:
        """解析 AI 的 JSON 回复，提取 replies 数组。最多3条。"""
        import json
        import re

        text = text.strip()
        if not text:
            return []

        # 尝试提取 JSON（可能混在 markdown 代码块中）
        # 先找 ```json ... ```
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            # 找最外层的大括号：用计数字符串匹配完整 JSON，避免 .*? 在嵌套 {} 时提前截断
            start = text.find("{")
            if start >= 0:
                depth = 0
                in_string = False
                escape_next = False
                for i in range(start, len(text)):
                    ch = text[i]
                    if escape_next:
                        escape_next = False
                        continue
                    if ch == "\\":
                        escape_next = True
                        continue
                    if ch == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            text = text[start:i+1]
                            break

        try:
            data = json.loads(text)
            replies = data.get("replies", [])
            if not isinstance(replies, list):
                replies = []
            # 过滤空字符串和敷衍词
            filtered = []
            for r in replies:
                r = str(r).strip()
                if not r or r in ("收到", "好的", "嗯", "OK", "1"):
                    continue
                filtered.append(r)
            return filtered[:3]
        except (json.JSONDecodeError, Exception):
            # JSON 解析失败，回退：把整段文本当作单条回复
            if text and text not in ("收到", "好的", "嗯", "OK", "1"):
                return [text]
            return []

    def _load_skill_manifest(self) -> List[Dict[str, str]]:
        """扫描 skills/ 目录，返回技能清单（name + trigger 描述），不含正文。"""
        from pathlib import Path
        skills_dir = Path(__file__).parent.parent.parent / "skills"
        if not skills_dir.exists():
            return []
        manifest = []
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            md_file = skill_dir / "SKILL.md"
            if md_file.exists():
                text = md_file.read_text(encoding="utf-8")
                # 提取第一行标题作为描述
                first_line = text.strip().split("\n")[0].replace("#", "").strip()
                manifest.append({
                    "name": skill_dir.name,
                    "description": first_line,
                })
        return manifest

    def _load_skill_content(self, skill_name: str) -> str:
        """加载指定 skill 的完整 SKILL.md 内容。"""
        from pathlib import Path
        md_file = Path(__file__).parent.parent.parent / "skills" / skill_name / "SKILL.md"
        if md_file.exists():
            return md_file.read_text(encoding="utf-8").strip()
        return ""

    def _route_skills(self, user_text: str) -> List[str]:
        """模型辅助路由：根据用户消息判断需要加载哪些 skill。
        用一次轻量 LLM 调用，只消耗几十 token。
        """
        if not user_text or not self.llm_client:
            return []

        manifest = self._load_skill_manifest()
        if not manifest:
            return []

        # 构建轻量路由 prompt
        skill_list = "\n".join(
            f"{i+1}. {s['name']}：{s['description']}"
            for i, s in enumerate(manifest)
        )
        router_prompt = (
            "你是 SkillRouter，只负责判断用户消息需要哪些技能。\n\n"
            f"可用技能：\n{skill_list}\n\n"
            f"用户消息：\"{user_text}\"\n\n"
            "请输出 JSON，只包含技能 name 列表，不要其他内容：\n"
            '{"skills": ["skill_name1", "skill_name2"]}\n'
            "如果不需要任何技能，输出：{\"skills\": []}"
        )

        try:
            # 记录路由请求到 trace
            if hasattr(self, 'last_generation_trace') and isinstance(self.last_generation_trace, list):
                self.last_generation_trace.append({
                    "round": 0,
                    "type": "skill_router_request",
                    "timestamp": time.time(),
                    "messages": [{"role": "user", "content": router_prompt[:500] + "..." if len(router_prompt) > 500 else router_prompt}],
                    "temperature": 0.0,
                    "max_tokens": 256,
                })
            raw = self.llm_client.chat(
                messages=[{"role": "user", "content": router_prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            raw_str = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
            # 记录路由响应到 trace
            raw_preview = (raw_str[:200]) if raw_str else ""
            if hasattr(self, 'last_generation_trace') and isinstance(self.last_generation_trace, list):
                self.last_generation_trace.append({
                    "round": 0,
                    "type": "skill_router_response",
                    "timestamp": time.time(),
                    "content": raw_preview,
                })
            # 尝试解析 JSON
            if raw_str:
                import json, re
                # 先尝试从 markdown 代码块中提取
                m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_str, re.DOTALL)
                if not m:
                    # 再找最外层的大括号（贪婪匹配，确保取完整 JSON）
                    m = re.search(r'\{.*\}', raw_str, re.DOTALL)
                if m:
                    json_text = m.group(1) if m.lastindex else m.group()
                    data = json.loads(json_text)
                    matched = data.get("skills", [])
                    # 过滤有效 skill
                    valid = {s["name"] for s in manifest}
                    result = [name for name in matched if name in valid]
                    print(f"[SkillRouter] 用户消息: {user_text[:30]}... -> 匹配技能: {result}")
                    return result
                else:
                    print(f"[SkillRouter] 用户消息: {user_text[:30]}... -> 未找到 JSON，原始响应: {raw_str[:100]}")
        except Exception as e:
            print(f"[SkillRouter] 路由异常: {type(e).__name__}: {e}")
            if hasattr(self, 'last_generation_trace') and isinstance(self.last_generation_trace, list):
                self.last_generation_trace.append({
                    "round": 0,
                    "type": "skill_router_error",
                    "timestamp": time.time(),
                    "error": f"{type(e).__name__}: {e}",
                })
        return []

    def _load_skill_one_liners(self) -> str:
        """加载所有 skill 的一句话摘要（始终放在 system prompt 中，极简）。
        从 SKILL.md 的'触发条件'段落提取第一句话。"""
        from pathlib import Path
        skills_dir = Path(__file__).parent.parent.parent / "skills"
        if not skills_dir.exists():
            return ""
        parts = []
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            md_file = skill_dir / "SKILL.md"
            if md_file.exists():
                text = md_file.read_text(encoding="utf-8").strip()
                if text.strip():
                    name = skill_dir.name
                    lines = text.split("\n")
                    summary = ""
                    in_trigger = False
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("## 触发条件"):
                            in_trigger = True
                            continue
                        if in_trigger:
                            if stripped.startswith("##") or not stripped:
                                break
                            summary = stripped
                            break
                    if summary:
                        # 截断到 40 字以内
                        if len(summary) > 40:
                            summary = summary[:37] + "..."
                        parts.append(f"- {name}：{summary}")
        if parts:
            return "\n可用技能（系统会根据对话内容自动下发详细框架）：\n" + "\n".join(parts) + "\n"
        return ""

    def _system_prompt(self) -> str:
        """核心 system prompt：人设 + 可用工具 + 规则。精简版。"""
        skill_hint = self._load_skill_one_liners()

        lines_local = [
            "核心人设与风格",
            "你没有固定人设。参照对方的说话风格自然融入对话。",
            '风格：casual，不用"您"，略带傲娇，适当幽默反转。',
            '口头禅：对方炫富/晒成就时可用"羡慕你们这些有钱人"、"被你装到了"等。',
            "不要重复自己之前说过的梗，每次回复都是新的。",
            "",
            "可用工具（系统会自动执行并返回结果）",
            "- get_current_time：获取当前日期和时间",
            "- get_weather(city, date)：查询天气",
            "- web_search(query)：搜索网页获取实时信息",
            "- browse_url(url)：打开链接提取网页正文。用户分享链接时使用。",
            "- stock_query(stock_code)：查询股票。支持A股sh600519、港股hk00700、美股AAPL",
            "- search_memory(query)：搜索本地长期记忆。涉及任何人名/称呼/关系时必须调用。",
            "",
            "输出格式",
            "需要工具时：按 function calling 格式输出 tool_calls。",
            "不需要工具时：直接输出 JSON {\"replies\": [\"回复1\"]}，不要 markdown 代码块。",
            "replies 数组包含 0-3 条，不需要回复时为空数组 []。",
            "绝对不要输出思考过程。",
            "",
            "规则",
            "1. 每条回复简洁自然，不超过50字",
            "2. 默认不回复，不确定时空 replies []",
            "3. 群聊没被@时不回复",
            "4. 禁止敷衍词：收到、好的、嗯、OK、1",
            "5. 不要重复之前的内容",
            "6. 对方发图片/表情包时，可以针对图片内容调侃或评价",
            "7. 对方发重复图片/表情包时，不要重复之前的评价",
        ]
        if skill_hint:
            lines_local.append("")
            lines_local.append(skill_hint.strip())
        return "\n".join(lines_local)

    def _build_tools_context(self, chat_name: str) -> str:
        """构建工具上下文：已缓存数据 + 工具结果提示。"""
        cache_lines = self.session_memory.get_cache_lines(chat_name, include_expired=True)
        if not cache_lines:
            return ""
        lines_local = ["已缓存数据（来自之前查询，无需重复调用）"]
        lines_local.extend(cache_lines)
        lines_local.append("")
        return "\n".join(lines_local)

    def _hermes_system_prompt(self) -> str:
        """hermes 专用 system prompt：不含 tool 列表，只保留风格+格式。"""
        return (
            "核心人设与风格\n"
            "你没有固定人设。参照对方的说话风格自然融入对话。\n"
            '风格：casual，不用"您"，略带傲娇，适当幽默反转。\n'
            '口头禅：对方炫富/晒成就时可用"羡慕你们这些有钱人"、"被你装到了"等。\n'
            "不要重复自己之前说过的梗，每次回复都是新的。\n"
            "\n"
            "你可以使用 skills_list 查看可用技能，用 skill_view 加载需要的技能。"
            "遇到专业领域的问题，先加载对应 skill 再回答。"
            "回复开头请用【Skill: xxx】标注使用了哪些 skill。"
            "\n\n"
            "输出格式\n"
            "直接输出 JSON（不要 markdown 代码块）：\n"
            '{\"replies\": [\"回复内容1\", \"回复内容2\"]}\n'
            "replies 数组包含 0-5 条，不需要回复时为空数组 []。\n"
            "绝对不要输出思考过程。\n"
            "\n"
            "规则\n"
            "1. 每条回复简洁自然，不超过300字\n"
            "2. 不懂、不确定的话题，输出空 replies []\n"
            "3. 禁止敷衍词：收到、好的、嗯、OK、1\n"
            "4. 参照对方语气回复，不要延续自己的风格\n"
            "5. 对方发图片/表情包时，可以针对图片内容调侃或评价\n"
            "6. 对方发重复图片/表情包时，不要重复之前的评价\n"
        )
    @staticmethod
    def _format_message_line(m: ChatMessage) -> str:
        """将单条消息渲染为 prompt 中的一行文本。"""
        sender_name = "我" if m.sender_type == SenderType.SELF else m.sender
        msg_type = m.message_type or "text"

        if msg_type == "image":
            desc = m.image_description or "图片"
            text_part = m.image_text or m.text or ""
            if text_part:
                return f"{sender_name}：[图片] {desc}（图上文字：{text_part}）"
            return f"{sender_name}：[图片] {desc}"

        elif msg_type == "sticker":
            desc = m.image_description or "表情包"
            text_part = m.image_text or m.text or ""
            if text_part:
                return f"{sender_name}：[表情包] {desc}（配字：{text_part}）"
            return f"{sender_name}：[表情包] {desc}"

        elif msg_type == "mixed":
            desc = m.image_description or ""
            text_part = m.text or ""
            if desc:
                return f"{sender_name}：[图片+文字] {text_part} | 图片描述：{desc}"
            return f"{sender_name}：[图片+文字] {text_part}"

        elif msg_type == "link_card":
            desc = m.image_description or "链接卡片"
            return f"{sender_name}：[链接卡片] {desc}"

        else:
            # text 或默认
            return f"{sender_name}：{m.text}"

    def _build_user_prompt(self, unreplied: List[ChatMessage], all_messages: List[ChatMessage]) -> str:
        """构建结构化 user prompt：会话信息 + 记忆 + 历史 + 未读。"""
        from datetime import datetime
        chat_name = unreplied[-1].chat_name if unreplied else ""
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        lines_local = []

        # 会话信息
        lines_local.append("[会话]")
        lines_local.append(f"时间：{now}")
        lines_local.append(f"聊天：{chat_name}")
        lines_local.append("")

        # wiki 记忆
        if self.memory_engine is not None and unreplied:
            from wechat_rpa.reply.policy import _is_group_chat
            is_group = _is_group_chat(chat_name)
            last_sender = unreplied[-1].sender
            if last_sender and last_sender != "我":
                memory_text = self.memory_engine.get_user_memory(last_sender, max_chars=2000)
                if memory_text and "（暂无）" not in memory_text:
                    lines_local.append("[对方信息]（来自长期记忆）")
                    lines_local.append(memory_text)
                    lines_local.append("")
            if is_group and chat_name:
                group_text = self.memory_engine.get_group_memory(chat_name, max_chars=2000)
                if group_text and "（暂无）" not in group_text:
                    lines_local.append("[本群信息]（来自长期记忆）")
                    lines_local.append(group_text)
                    lines_local.append("")

        # 历史消息
        if all_messages:
            lines_local.append("[历史消息]（仅背景参考）")
            self_messages = [m for m in all_messages if m.sender_type == SenderType.SELF]
            kept_self = self_messages[-3:] if len(self_messages) > 3 else self_messages
            skipped_self_count = len(self_messages) - len(kept_self)

            for m in all_messages:
                if m.sender_type == SenderType.SELF and m not in kept_self:
                    continue
                lines_local.append(self._format_message_line(m))

            if skipped_self_count > 0:
                lines_local.append(f"（省略了之前自己发的 {skipped_self_count} 条）")
            lines_local.append("")

        # 未读消息
        lines_local.append("[未读消息]（重点回复）")
        for i, m in enumerate(unreplied, 1):
            lines_local.append(f"{i}. {self._format_message_line(m)}")
        lines_local.append("")
        lines_local.append("提示：回复重点放在[未读消息]，历史只是背景。不确定时空 replies []。")

        return "\n".join(lines_local)
    def _clean_reply(self, text: str) -> str:
        """不再做思考内容过滤。若 LLM 输出思考过程，问题应在 prompt/LLM 层解决。"""
        text = text.strip()
        # 如果 LLM 返回空或只包含被禁止的敷衍词，视为无效回复
        if not text or text in ("收到", "好的", "嗯", "OK", "1"):
            return ""
        return text

    def _fallback_reply(self, msg: ChatMessage) -> str:
        """兜底回复：已废弃，直接返回空字符串（不回复）。
        经验表明，硬编的兜底话术不如不说。"""
        return ""
