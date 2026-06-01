#!/usr/bin/env python3
"""L4 Reply Generator - 回复内容生成."""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models.base import ChatMessage, SenderType
from src.tools import get_registry, register_builtin_tools
from src.reply.session_memory import SessionMemory, _extract_query_key

_logger = logging.getLogger("src.reply.generator")

# Badcase JudgeWorker（可选，默认不启用）
import threading
_judge_worker = None
_judge_worker_lock = threading.Lock()

def _get_judge_worker():
    global _judge_worker
    if _judge_worker is None:
        with _judge_worker_lock:
            if _judge_worker is None:
                try:
                    from src.badcase.judge_worker import JudgeWorker
                    _judge_worker = JudgeWorker()
                    _logger.info("JudgeWorker initialized")
                except Exception as e:
                    _logger.warning("JudgeWorker init failed: %s", e)
    return _judge_worker


class ReplyGenerator:
    def __init__(self, llm_client=None, complex_llm_client=None, memory_engine=None,
                 tool_registry=None,
                 judge_worker=None,
                 enable_time_awareness: bool = True,
                 enable_reply_restraint: bool = True,
                 enable_unread_dedup: bool = True,
                 enable_timestamps: bool = True):
        self.llm_client = llm_client
        self.complex_llm_client = complex_llm_client
        self.memory_engine = memory_engine
        self.tool_registry = tool_registry or get_registry()
        self.judge_worker = judge_worker
        self.enable_time_awareness = enable_time_awareness
        self.enable_reply_restraint = enable_reply_restraint
        self.enable_unread_dedup = enable_unread_dedup
        self.enable_timestamps = enable_timestamps
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
        # 传给 Judge 的完整 LLM 上下文
        self.last_llm_messages: List[Dict] = []
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

    def _submit_to_judge(self, tick_id: int, replies: List[str], unreplied: List[ChatMessage], all_messages: List[ChatMessage], is_group: bool):
        """把当前 tick 的数据提交给 JudgeWorker 异步判定"""
        import json
        try:
            worker = self.judge_worker
            if worker is None:
                return
            tick_data = {
                "tick_id": tick_id,
                "chat_name": unreplied[-1].chat_name if unreplied else "",
                "session_input_messages": [
                    {
                        "sender": m.sender,
                        "sender_type": m.sender_type.value,
                        "text": m.text or "",
                        "chat_name": m.chat_name,
                    }
                    for m in all_messages
                ],
                "bot_reply_text": " | ".join(replies) if replies else "",
                "reply_text": " | ".join(replies) if replies else "",
                "tool_calls": self.last_tool_calls,
                "memory_injected": self.last_user_prompt,
                "full_user_prompt": self.last_user_prompt,
                "reply_raw_response": self.last_raw_response,
                "reply_generation_trace": self.last_generation_trace,
                "full_system_prompt": self.last_system_prompt,
                "full_tools_context": self.last_tools_context,
                "full_llm_messages": self.last_llm_messages,
                "created_at": __import__('datetime').datetime.now().isoformat(),
                "tool_results_json": json.dumps(
                    [{"tool": t.get("tool_name", ""), "args": t.get("arguments", ""), "result": str(t.get("result_preview", ""))}
                     for t in (self.last_tool_calls or [])], ensure_ascii=False
                ),
            }
            worker.submit(tick_data)
        except Exception as e:
            _logger.debug("JudgeWorker submit failed: %s", e)

    def generate(self, unreplied: List[ChatMessage], all_messages: List[ChatMessage],
                 is_group: bool = False, tick_id: int = 0,
                 enable_time_awareness: bool = None,
                 enable_reply_restraint: bool = None,
                 enable_unread_dedup: bool = None,
                 enable_timestamps: bool = None) -> List[str]:
        """
        生成回复内容，返回多条回复列表（最多3条）。
        支持多轮工具调用，但总工具时间不超过 max_tool_seconds，超时后强制生成文本回复。
        """
        t_generate_start = time.time()
        if not unreplied:
            self._submit_to_judge(tick_id, [], unreplied, all_messages, is_group)
            return []

        fallback_msg = unreplied[-1]

        if self.llm_client is None:
            self._submit_to_judge(tick_id, [], unreplied, all_messages, is_group)
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
        self.last_llm_messages = []

        chat_name = unreplied[-1].chat_name if unreplied else ""

        t_sp_start = time.time()
        system_prompt = self._system_prompt(enable_reply_restraint=enable_reply_restraint)
        t_sp_ms = (time.time() - t_sp_start) * 1000

        t_tc_start = time.time()
        tools_context = self._build_tools_context(chat_name)
        t_tc_ms = (time.time() - t_tc_start) * 1000

        t_up_start = time.time()
        user_prompt = self._build_user_prompt(
            unreplied, all_messages, is_group,
            enable_time_awareness=enable_time_awareness,
            enable_unread_dedup=enable_unread_dedup,
            enable_timestamps=enable_timestamps,
            tools_context=tools_context,
        )
        t_up_ms = (time.time() - t_up_start) * 1000

        # 模型辅助路由：按需加载匹配的 skill 正文到 user prompt
        last_msg = unreplied[-1]
        route_text = last_msg.text or last_msg.image_description or ""
        t_route_start = time.time()
        matched_skills = self._route_skills(route_text)
        t_route_ms = (time.time() - t_route_start) * 1000
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
        max_tool_seconds = 25.0  # 工具调用阶段最多 25 秒
        max_total_seconds = 600.0 if is_hermes else 60.0  # deepseek 给 60 秒，给工具调用留余量
        overall_start_time = time.time()

        # 构建 messages：system（人设）+ user（上下文含缓存）
        messages = [{"role": "system", "content": system_prompt}]
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
                    _logger.info("[LLM] attempt=%d round=%d force_no_tools=%s tools=%s timeout=%s msg_count=%d",
                                 attempt + 1, tool_round_count, force_no_tools, bool(actual_tools), llm_timeout, len(messages))
                    t_llm_start = time.time()
                    raw = active_llm.chat(messages=messages, tools=actual_tools, max_tokens=2000, timeout=llm_timeout)
                    self.last_llm_messages = [dict(m) for m in messages]
                    t_llm_ms = (time.time() - t_llm_start) * 1000
                    raw_content = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
                    raw_tool_calls = getattr(raw, "tool_calls", None)
                    _logger.info("[LLM] attempt=%d round=%d 完成 耗时=%.0fms type=%s",
                                 attempt + 1, tool_round_count, t_llm_ms,
                                 "tool_calls" if raw_tool_calls else "text")

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
                        # DeepSeek thinking mode 需要回传 reasoning_content，否则 round 1 会空返
                        if hasattr(raw, "reasoning_content") and raw.reasoning_content:
                            assistant_msg["reasoning_content"] = raw.reasoning_content
                        messages.append(assistant_msg)

                        for tc in raw_tool_calls:
                            tool_name = tc.function.name
                            tool_args = tc.function.arguments
                            _logger.info("[Tool] 执行开始: %s(%s)", tool_name, tool_args[:100] if isinstance(tool_args, str) else str(tool_args)[:100])
                            t_tool_start = time.time()
                            if self.tool_registry.has(tool_name):
                                result = self.tool_registry.get(tool_name).execute(tool_args)
                            else:
                                result = f"工具 {tool_name} 不存在"
                            t_tool_ms = (time.time() - t_tool_start) * 1000
                            _logger.info("[Tool] 执行完成: %s 耗时=%.0fms result_len=%d", tool_name, t_tool_ms, len(str(result)) if result else 0)

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
                                "result_preview": str(result) if result else "",
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
                    t_parse_start = time.time()
                    replies = self._parse_replies(text)
                    t_parse_ms = (time.time() - t_parse_start) * 1000
                    if replies:
                        model_name = "hermes" if active_llm is self.complex_llm_client else "deepseek"
                        t_total_ms = (time.time() - t_generate_start) * 1000
                        print(f"[Perf][Generate] total={t_total_ms:.0f}ms "
                              f"sp={t_sp_ms:.0f}ms tc={t_tc_ms:.0f}ms up={t_up_ms:.0f}ms "
                              f"route={t_route_ms:.0f}ms llm={sum(c.get('elapsed',0) for c in llm_calls)*1000:.0f}ms "
                              f"parse={t_parse_ms:.0f}ms replies={len(replies)}")
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
                        self._submit_to_judge(tick_id, replies, unreplied, all_messages, is_group)
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
                        self.last_llm_messages = [dict(m) for m in hermes_messages]
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
                            self._submit_to_judge(tick_id, hermes_replies, unreplied, all_messages, is_group)
                            return hermes_replies
                        # hermes 也返回空 → fallback 到不回复
                        print(f"[Hermes] 返回空 replies")
                        self.last_llm_calls = llm_calls
                        self.last_tool_calls = tool_calls
                        self.last_generation_trace.extend(trace)
                        self._submit_to_judge(tick_id, [], unreplied, all_messages, is_group)
                        return []

                    # LLM 明确输出了 {"replies": []} → 正确决策（不想回复），不 retry
                    if text and '"replies"' in text:
                        print(f"[Hermes] LLM 输出空 replies → 正确决策不回复")
                        self.last_llm_calls = llm_calls
                        self.last_tool_calls = tool_calls
                        self.last_generation_trace.extend(trace)
                        self._submit_to_judge(tick_id, [], unreplied, all_messages, is_group)
                        return []

                    # 空回复处理（LLM 返回空字符串或无效内容）
                    if force_no_tools:
                        # 禁用 tools 后返回空，可能是 LLM 还在尝试调用工具
                        # 继续外层 retry，给 LLM 一次基于已有信息直接回复的机会
                        print(f"[Hermes] force_no_tools 空回复，继续 retry")
                        self.last_raw_response = f"[空回复且已禁用tools，attempt={attempt+1}]"
                        break  # 跳出 while，进入下一次 retry

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
        self._submit_to_judge(tick_id, [], unreplied, all_messages, is_group)
        return []

    def _truncate_messages(self, messages: List[Dict]) -> List[Dict]:
        """截断 OpenAI message 数组，防止 debug JSON 过大。

        注意：此函数处理的是 List[Dict] 结构（含 content + tool_calls），
        与通用 text_utils._truncate_text（处理 str）不同，因此保留独立实现。
        阈值设高些，markdown 会单独保存完整版。
        """
        truncated = []
        for m in messages:
            cm = dict(m)
            if "content" in cm and isinstance(cm["content"], str) and len(cm["content"]) > 10000:
                cm["content"] = cm["content"][:10000] + "\n\n... [truncated, see markdown for full content]"
            if "tool_calls" in cm:
                cm["tool_calls"] = [{"id": tc.get("id"), "name": tc.get("function", {}).get("name")} for tc in cm["tool_calls"]]
            truncated.append(cm)
        return truncated

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict]:
        """从 LLM 回复中提取 JSON 对象。支持 markdown 代码块和裸 JSON。
        使用括号深度计数找 JSON 边界，避免正则贪婪匹配截断问题。
        """
        import json
        text = text.strip()
        if not text:
            return None
        # 去掉 markdown 代码块
        if "```" in text:
            parts = text.split("```", 2)
            if len(parts) >= 3:
                code_content = parts[1]
                # 去掉可能的 "json" 语言标记
                if code_content.lstrip().startswith("json"):
                    code_content = code_content.lstrip()[4:].lstrip()
                text = code_content
        # 找 JSON 边界（括号深度计数）
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    def _parse_replies(self, text: str) -> List[str]:
        """解析 LLM 回复：{"replies": ["msg1", "msg2"]}。prompt 已要求此格式。"""
        data = self._extract_json(text)
        if data is not None:
            replies = data.get("replies", [])
            return [str(r).strip() for r in replies if str(r).strip() not in ("收到", "好的", "嗯", "OK", "1")][:3]
        # fallback: 按段落拆分，不再整段当一条发
        text = text.strip()
        for sep in ("\n\n", "\n"):
            parts = [p.strip().replace("\n", " ") for p in text.split(sep) if p.strip()]
            if len(parts) > 1:
                return [p for p in parts if p not in ("收到", "好的", "嗯", "OK", "1")][:3]
        return [text.replace("\n", " ")] if text not in ("收到", "好的", "嗯", "OK", "1") else []

    def _load_skill_manifest(self) -> List[Dict[str, str]]:
        """扫描 skills/ 目录，返回技能清单（name + trigger 描述），不含正文。"""
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
                data = self._extract_json(raw_str)
                if data is not None:
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

    def _system_prompt(self, enable_reply_restraint: bool = None) -> str:
        """核心 system prompt：读 prompts/persona.md（DT 风格），注入工具描述 + 检索案例。"""
        if enable_reply_restraint is None:
            enable_reply_restraint = self.enable_reply_restraint

        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "persona.md"
        if prompt_path.exists():
            prompt = prompt_path.read_text(encoding="utf-8")
        else:
            prompt = "你是王芊本人。用户不是在跟AI聊天，是在微信上给王芊发消息。"

        # 根据开关删除回复克制原则 section
        if not enable_reply_restraint:
            marker = "### 7. 回复克制原则"
            idx = prompt.find(marker)
            if idx != -1:
                next_section = prompt.find("### ", idx + 1)
                if next_section != -1:
                    prompt = prompt[:idx] + prompt[next_section:]
                else:
                    prompt = prompt[:idx]

        # 注入工具描述
        tools_desc = "\n".join(
            f"- {t.name}：{t.description}"
            for t in self.tool_registry._tools.values()
        )
        prompt = prompt.replace("{tools_description}", tools_desc)

        # 注入检索 few-shot
        prompt = prompt.replace("{dynamic_few_shot}", "（无相关历史对话）")

        # 保留 skill hint
        skill_hint = self._load_skill_one_liners()
        if skill_hint:
            prompt += "\n\n" + skill_hint.strip()
        return prompt

    def _build_tools_context(self, chat_name: str) -> str:
        """构建工具上下文：已缓存数据 + 工具结果提示。"""
        cache_lines = self.session_memory.get_cache_lines(chat_name, include_expired=True)
        if not cache_lines:
            return ""
        lines_local = ["已缓存数据（来自之前查询，无需重复调用）"]
        lines_local.extend(cache_lines)
        lines_local.append("")
        return "\n".join(lines_local)

    @staticmethod
    def _format_time_tag(ts: Optional[int], now_ts: float) -> str:
        """根据时间戳生成绝对时间标签 YYYY-MM-DD HH:MM。"""
        if not ts:
            return ""
        tm = time.localtime(int(ts))
        return f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d} {tm.tm_hour:02d}:{tm.tm_min:02d}"

    @staticmethod
    def _format_message_line(m: ChatMessage, enable_timestamps: bool = True) -> str:
        """将单条消息渲染为 prompt 中的一行文本，含时间戳。"""
        sender_name = "我" if m.sender_type == SenderType.SELF else m.sender
        msg_type = m.message_type or "text"
        now_ts = time.time()

        # 时间标签（优先 create_time int，fallback timestamp str）
        time_tag = ""
        if enable_timestamps:
            ts = getattr(m, 'create_time', None)
            if not ts:
                ts_str = getattr(m, 'timestamp', None)
                if ts_str:
                    try:
                        from datetime import datetime
                        ts = int(datetime.strptime(ts_str.replace('  ', ' '), "%Y-%m-%d %H:%M:%S").timestamp())
                    except Exception as e:
                        _logger.warning("[Generator] 时间戳解析失败: %s (raw=%r)", e, ts_str)
            time_tag = ReplyGenerator._format_time_tag(ts, now_ts) if ts else ""

        def _line(body: str) -> str:
            if time_tag:
                return f"{sender_name}（{time_tag}）：{body}"
            return f"{sender_name}：{body}"

        if msg_type == "image":
            desc = m.image_description or "图片"
            text_part = m.image_text or m.text or ""
            if text_part:
                return _line(f"[图片] {desc}（图上文字：{text_part}）")
            return _line(f"[图片] {desc}")

        elif msg_type == "sticker":
            desc = m.image_description or "表情包"
            text_part = m.image_text or m.text or ""
            if text_part:
                return _line(f"[表情包] {desc}（配字：{text_part}）")
            return _line(f"[表情包] {desc}")

        elif msg_type == "mixed":
            desc = m.image_description or ""
            text_part = m.text or ""
            if desc:
                return _line(f"[图片+文字] {text_part} | 图片描述：{desc}")
            return _line(f"[图片+文字] {text_part}")

        elif msg_type == "link_card":
            desc = m.image_description or "链接卡片"
            return _line(f"[链接卡片] {desc}")

        elif msg_type == "video":
            desc = m.image_description or "视频"
            text_part = m.image_text or m.text or ""
            if text_part:
                return _line(f"[视频] {desc}（视频文字：{text_part}）")
            return _line(f"[视频] {desc}")

        else:
            return _line(m.text)

    def _build_user_prompt(self, unreplied: List[ChatMessage], all_messages: List[ChatMessage],
                           is_group: bool = False,
                           enable_time_awareness: bool = None,
                           enable_unread_dedup: bool = None,
                           enable_timestamps: bool = None,
                           tools_context: str = "") -> str:
        """构建结构化 user prompt：会话信息 + 记忆 + 缓存 + 历史 + 未读。"""
        if enable_time_awareness is None:
            enable_time_awareness = self.enable_time_awareness
        if enable_unread_dedup is None:
            enable_unread_dedup = self.enable_unread_dedup
        if enable_timestamps is None:
            enable_timestamps = self.enable_timestamps

        from datetime import datetime
        chat_name = unreplied[-1].chat_name if unreplied else ""
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        lines_local = []

        # 会话信息（含时间上下文）
        is_at = any(getattr(m, "is_at_me", False) for m in unreplied)
        chat_type = "群聊" if is_group else "私聊"
        now_dt = datetime.now()
        now = now_dt.strftime("%Y年%m月%d日 %H:%M")
        weekday = ["周一","周二","周三","周四","周五","周六","周日"][now_dt.weekday()]
        hour = now_dt.hour
        time_period = "凌晨" if hour < 6 else ("早上" if hour < 9 else ("上午" if hour < 12 else ("下午" if hour < 18 else ("晚上" if hour < 22 else "深夜"))))
        lines_local.append("[会话]")
        if enable_time_awareness:
            lines_local.append(f"当前时间：{now} {weekday} {time_period}")
        lines_local.append(f"聊天：{chat_name}")
        lines_local.append(f"类型：{chat_type}")
        lines_local.append(f"被@：{'是' if is_at else '否'}")
        lines_local.append("")
        if enable_time_awareness:
            lines_local.append("⚠️ 消息时间戳说明：每条消息后面标注的时间是消息发出的绝对时间（格式：YYYY-MM-DD HH:MM）。请根据时间戳推断语境，不要假设消息是刚刚发的。")
            lines_local.append("")

        # wiki 记忆
        t_mem_ms = {}
        if self.memory_engine is not None and unreplied:
            # 固定注入 Bot 自己的 wiki，避免 LLM 被对方的 wiki 淹没后混淆身份
            t_m1 = time.time()
            self_memory = self.memory_engine.get_user_memory("王芊", max_chars=4000)
            t_mem_ms["self"] = (time.time() - t_m1) * 1000
            if self_memory and "（暂无）" not in self_memory:
                lines_local.append("[我的信息]（来自长期记忆，Bot 自己的身份背景）")
                lines_local.append(self_memory)
                lines_local.append("")

            last_sender = unreplied[-1].sender
            # 去除 @群名 后缀，提取纯用户名用于 wiki 查询
            clean_sender = last_sender.split(" @")[0] if last_sender and " @" in last_sender else last_sender
            if clean_sender and clean_sender != "我":
                t_m2 = time.time()
                memory_text = self.memory_engine.get_user_memory(clean_sender, max_chars=6000)
                t_mem_ms["other"] = (time.time() - t_m2) * 1000
                if memory_text and "（暂无）" not in memory_text:
                    lines_local.append("[对方信息]（来自长期记忆，仅为该用户记忆的部分摘要）")
                    lines_local.append(memory_text)
                    lines_local.append("")
            if is_group and chat_name:
                t_m3 = time.time()
                group_text = self.memory_engine.get_group_memory(chat_name, max_chars=6000)
                t_mem_ms["group"] = (time.time() - t_m3) * 1000
                if group_text and "（暂无）" not in group_text:
                    lines_local.append("[本群信息]（来自长期记忆）")
                    lines_local.append(group_text)
                    lines_local.append("")

            # 跨 wiki 搜索：扫描未读消息中提到的人名/alias，grep 所有 wiki
            if unreplied:
                t_m4 = time.time()
                mention_text = " ".join(m.text or "" for m in unreplied)
                related = self.memory_engine.search_related_mentions(
                    mention_text, exclude_user=clean_sender if clean_sender and clean_sender != "我" else None, max_files=10
                )
                t_mem_ms["mentions"] = (time.time() - t_m4) * 1000
                if related:
                    lines_local.append("[相关背景]（来自其他聊天记录）")
                    for r in related:
                        lines_local.append(r)
                    lines_local.append("")

            mem_summary = " ".join(f"{k}={v:.0f}ms" for k, v in t_mem_ms.items())
            print(f"[Perf][Memory] {mem_summary}")

        # 已缓存数据（session_memory 中的工具结果）
        if tools_context:
            lines_local.append(tools_context)
            lines_local.append("")

        # 历史消息：最近50条 或 最近30分钟内，取并集
        if all_messages:
            lines_local.append("[历史消息]（仅背景参考，按时间倒序）")

            def _msg_ts(m: ChatMessage) -> float:
                if m.sender_type == SenderType.SELF and m.reply_time:
                    return m.reply_time
                if m.create_time:
                    return float(m.create_time)
                return time.time()

            now_ts = time.time()
            cutoff_ts = now_ts - 1800  # 30分钟

            recent_50 = list(all_messages[-50:]) if len(all_messages) > 50 else list(all_messages)
            recent_30min = [m for m in all_messages if _msg_ts(m) >= cutoff_ts]

            union_ids = {id(m) for m in recent_50} | {id(m) for m in recent_30min}
            candidate = [m for m in all_messages if id(m) in union_ids]

            # 兜底：强制保留最近 5 条 bot 自己发的消息，防止被对方密集消息淹没
            self_msgs = [m for m in all_messages if m.sender_type == SenderType.SELF]
            for m in self_msgs[-5:]:
                union_ids.add(id(m))
            candidate = [m for m in all_messages if id(m) in union_ids]

            max_history = 80
            recent = list(candidate[-max_history:]) if len(candidate) > max_history else list(candidate)
            # 保持正序：旧的消息在前，新的消息在后，符合阅读习惯

            for m in recent:
                lines_local.append(self._format_message_line(m, enable_timestamps))

            if len(all_messages) > len(recent):
                lines_local.append(f"（共 {len(all_messages)} 条历史，显示 {len(recent)} 条：最近50条 + 30分钟内）")
            lines_local.append("")

        # 未读消息（带去重检查：如果历史中已有相似消息且 Bot 已回复，标记为'可能已处理'）
        lines_local.append("[未读消息]（重点回复）")
        # 从历史中提取 Bot 已回复的消息文本（用于去重判断）
        replied_in_history = set()
        if all_messages:
            for m in all_messages:
                if m.sender_type == SenderType.SELF and m.reply_time and m.text:
                    # 提取 Bot 回复之前最后一个非 Bot 消息的文本作为"已处理"标记
                    pass
            # 简化：如果[未读消息]中的某条在[历史消息]中能找到 Bot 的回复且 Bot 回复在未读消息时间之前
            # 则标记为"可能已回复"

        skipped_hint = []
        for i, m in enumerate(unreplied, 1):
            ts = getattr(m, 'create_time', None)
            # 检查历史中是否有 Bot 在未读消息时间之后回复的
            already_handled = False
            if ts and all_messages:
                for hm in all_messages:
                    if hm.sender_type == SenderType.SELF and hm.reply_time and hm.reply_time > ts:
                        # Bot 在未读消息之后回复了，说明这条可能已经处理过
                        already_handled = True
                        break
            tag = " ⚠️(历史中已有回复，可跳过)" if (enable_unread_dedup and already_handled) else ""
            lines_local.append(f"{i}. {self._format_message_line(m, enable_timestamps)}{tag}")
            if enable_unread_dedup and already_handled:
                skipped_hint.append(str(i))
        lines_local.append("")

        if enable_unread_dedup and skipped_hint:
            lines_local.append(f"提示：第{','.join(skipped_hint)}条未读消息在历史中已有回复，可能不需要再次回复。仅回复真正未处理的新消息。")
        lines_local.append("回复重点：仅回复真正需要回应的未读消息。纯表情/OK/好的等确认性消息可以不回复。")

        return "\n".join(lines_local)
