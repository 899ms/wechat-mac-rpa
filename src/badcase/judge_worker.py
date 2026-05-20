#!/usr/bin/env python3
"""
JudgeWorker - 异步 badcase 判定与自动入库

生产运行时：
  1. ReplyGenerator.generate() 返回后，调用 submit() 把 tick_data 丢进队列
  2. submit() 立即返回（<1ms），不阻塞主循环
  3. 后台单线程协程消费队列，调用 LLM Judge
  4. 高置信度 → 自动追加到 benchmark
  5. 低置信度 → 写入 data/review_drafts/pending/

审核台运行时：
  - 读取 pending/ 下的 draft JSON
  - 人工确认后入库或丢弃
"""

import json
import logging
import os
import py_compile
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .case_generator import CaseGenerator

_logger = logging.getLogger("src.badcase.judge_worker")

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 自动入库硬编码规则
AUTO_COMMIT_RULES = {
    "min_confidence": 0.90,
    "allowed_types": {"missing_tool_call", "hallucination", "wrong_fact"},
}

# Judge Prompt（要求 LLM 输出结构化 JSON）
_JUDGE_PROMPT_TEMPLATE = """你是对话质量审计专家。判断以下 Bot 回复是否有质量问题，需要记录到 benchmark。

## 判定原则
- 重点关注：Bot 是否编造了记忆中没有的具体事实？是否该调工具没调？是否纠正后不生效？
- 区分"角色扮演自嘲"和"真错了"：Bot 说"我瞎编的"如果是在承认错误，是正常行为，不是 badcase
- 区分"玩笑"和"事实陈述"：如果 Bot 明确在调侃，即使内容夸张也不算 badcase

## 输入信息
{conversation_context}

## Bot 本轮回复
{bot_reply}

## Bot 实际收到的完整 User Prompt（含记忆注入、历史消息、未读消息）
{full_user_prompt}

## Bot 本轮调用的工具列表
{tool_calls}

## Bot 实际看到的完整上下文（关键！）
{full_context}

## 输出格式（纯 JSON，不要 markdown）
{{
  "is_badcase": true | false,
  "badcase_type": "hallucination" | "missing_tool_call" | "correction_not_persistent" | "wrong_fact" | "none",
  "severity": "P0" | "P1" | "P2",
  "confidence": 0.0 ~ 1.0,
  "auto_commit": true | false,
  "reason": "一句话理由，引用 Bot 回复原文作为证据",
  "expected_behavior": "Bot 应该怎么做才对？"
}}

## auto_commit 规则
- true：你非常确定这是 badcase，证据明确无歧义，不需要人工审核
- false：情况有模糊性，或涉及隐私判断，建议人工确认
"""


def _get_qwen_client():
    """延迟导入，避免循环依赖"""
    from src.utils.qwen_client import QwenClient
    return QwenClient(model="deepseek-v4-flash")


class JudgeWorker:
    """异步 badcase 判定 worker（基于 threading，适配 Bot 同步主循环）"""

    def __init__(self, model: str = "deepseek-v4-flash"):
        self.client = _get_qwen_client()
        self.queue: queue.Queue = queue.Queue()
        self._running = False
        self._consumer_thread: Optional[threading.Thread] = None
        self.case_generator = CaseGenerator()
        self._pending_dir = PROJECT_ROOT / "data" / "review_drafts" / "pending"
        self._committed_dir = PROJECT_ROOT / "data" / "review_drafts" / "committed"
        self._dismissed_dir = PROJECT_ROOT / "data" / "review_drafts" / "dismissed"
        self._auto_cases_dir = PROJECT_ROOT / "src" / "tests" / "fixtures" / "auto_cases"
        for d in (self._pending_dir, self._committed_dir, self._dismissed_dir, self._auto_cases_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 公共 API：主循环调用
    # ------------------------------------------------------------------
    def submit(self, tick_data: dict):
        """提交一个 tick 给判定队列，立即返回，不阻塞"""
        if not self._running:
            self._start()
        self.queue.put(tick_data)

    def shutdown(self):
        """优雅关闭"""
        self._running = False
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=5)

    # ------------------------------------------------------------------
    # 内部：后台消费线程
    # ------------------------------------------------------------------
    def _start(self):
        if self._running:
            return
        self._running = True
        self._consumer_thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._consumer_thread.start()
        _logger.info("JudgeWorker started (threading)")

    def _consume_loop(self):
        while self._running:
            try:
                tick_data = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._process_one(tick_data)
            except Exception as e:
                _logger.exception("JudgeWorker process tick %s failed: %s", tick_data.get("tick_id"), e)
                # 失败时把原始 tick_data 写入 unjudged，避免丢失
                self._save_unjudged(tick_data, str(e))
            finally:
                self.queue.task_done()

    def _process_one(self, tick_data: dict):
        tick_id = tick_data.get("tick_id", 0)
        _logger.info("[Judge] processing tick %s", tick_id)

        # 1. 调用 LLM Judge
        judge_result = self._judge(tick_data)
        if not judge_result.get("is_badcase"):
            _logger.info("[Judge] tick %s is not badcase", tick_id)
            return

        # 2. 构建 draft
        draft = self._build_draft(tick_data, judge_result)

        # 3. 生成 case 代码（用于自动入库或审核）
        generated = self.case_generator.generate(draft)
        draft["generated_case"] = generated

        # 4. 判定是否自动入库
        if self._should_auto_commit(judge_result):
            _logger.info("[Judge] tick %s auto_commit → %s", tick_id, generated["module"])
            self._auto_commit(draft)
        else:
            _logger.info("[Judge] tick %s → pending", tick_id)
            self._save_pending(draft)

    # ------------------------------------------------------------------
    # 内部：LLM Judge
    # ------------------------------------------------------------------
    def _judge(self, tick_data: dict) -> dict:
        """调用 LLM Judge，返回结构化 dict"""
        prompt = self._build_judge_prompt(tick_data)
        # 在线程中同步调用 LLM
        raw = self.client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
            timeout=30,
        )
        return self._parse_judge_response(raw)

    def _build_judge_prompt(self, tick_data: dict) -> str:
        # 提取对话上下文（最近 5 轮）
        conversation = tick_data.get("conversation", [])
        if not conversation:
            # 从 session_input_messages 转换
            messages = tick_data.get("session_input_messages", [])
            conversation = []
            for m in messages:
                role = "bot" if m.get("sender_type") == "self" else "user"
                conversation.append({"role": role, "text": m.get("text", "")})
        conversation_lines = []
        for i, turn in enumerate(conversation[-5:]):
            prefix = "Bot" if turn.get("role") == "bot" else f"User({turn.get('sender','')})"
            conversation_lines.append(f"{prefix}: {turn.get('text','')}")
        conversation_text = "\n".join(conversation_lines) if conversation_lines else "(无)"

        bot_reply = tick_data.get("bot_reply_text", "") or tick_data.get("reply_text", "")
        full_user_prompt = tick_data.get("full_user_prompt", "") or tick_data.get("memory_injected", "")
        tool_calls = tick_data.get("tool_calls", [])
        if not tool_calls:
            # 从 reply_generation_trace 提取
            trace = tick_data.get("reply_generation_trace", [])
            for t in trace:
                if t.get("type") == "llm_response":
                    tc = t.get("tool_calls", [])
                    if tc:
                        tool_calls = tc
                        break
        tool_calls_text = json.dumps(tool_calls, ensure_ascii=False, indent=2) if tool_calls else "[]"

        # Bot 实际看到的完整上下文（system prompt + tools + 完整 messages）
        full_context = self._build_full_context_for_judge(tick_data)

        return _JUDGE_PROMPT_TEMPLATE.format(
            conversation_context=conversation_text,
            bot_reply=bot_reply,
            full_user_prompt=full_user_prompt[:3000],
            tool_calls=tool_calls_text,
            full_context=full_context,
        )

    def _build_full_context_for_judge(self, tick_data: dict) -> str:
        """构建 Bot 实际看到的完整上下文，供 Judge 判定。做截断控制长度。"""
        system_prompt = tick_data.get("full_system_prompt", "")
        tools_context = tick_data.get("full_tools_context", "")
        llm_messages = tick_data.get("full_llm_messages", [])

        lines = []
        if system_prompt:
            lines.append("【System Prompt】")
            lines.append(system_prompt[:2000])
            lines.append("")

        if tools_context:
            lines.append("【Tools 定义（Bot 可用的工具）】")
            lines.append(tools_context[:2000])
            lines.append("")

        if llm_messages:
            lines.append("【LLM 实际接收的完整 Messages 列表】")
            # 截断：最多 10 条，每条 content 最多 500 字符
            truncated_msgs = []
            for m in llm_messages[-10:]:
                cm = dict(m)
                if "content" in cm and isinstance(cm["content"], str) and len(cm["content"]) > 500:
                    cm["content"] = cm["content"][:500] + "... [truncated]"
                # tool_calls 也做截断
                if "tool_calls" in cm and cm["tool_calls"]:
                    cm["tool_calls"] = [{"id": tc.get("id"), "name": tc.get("function", {}).get("name")}
                                          for tc in cm["tool_calls"]]
                truncated_msgs.append(cm)
            lines.append(json.dumps(truncated_msgs, ensure_ascii=False, indent=2))
        else:
            lines.append("【LLM Messages】无（未记录）")

        return "\n".join(lines)

    def _parse_judge_response(self, raw: str) -> dict:
        """解析 Judge LLM 返回的 JSON"""
        if not raw:
            return {"is_badcase": False, "reason": "Judge 返回空"}
        text = raw.strip()
        # 移除 markdown 代码块
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        # 找 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            _logger.warning("Judge JSON parse failed, raw=%s", raw[:200])
            return {"is_badcase": False, "reason": "JSON 解析失败"}

        # 规范化
        return {
            "is_badcase": bool(data.get("is_badcase")),
            "badcase_type": data.get("badcase_type", "none"),
            "severity": data.get("severity", "P2"),
            "confidence": float(data.get("confidence", 0.0)),
            "auto_commit": bool(data.get("auto_commit")),
            "reason": data.get("reason", ""),
            "expected_behavior": data.get("expected_behavior", ""),
        }

    # ------------------------------------------------------------------
    # 内部：draft 构建
    # ------------------------------------------------------------------
    def _build_draft(self, tick_data: dict, judge_result: dict) -> dict:
        tick_id = tick_data.get("tick_id", 0)
        timestamp = tick_data.get("timestamp", datetime.now().isoformat())
        draft_id = f"tick_{tick_id}_{timestamp.replace(':', '-').replace('.', '_')}"

        # 构造对话历史
        conversation = []
        session_msgs = tick_data.get("session_input_messages", [])
        for m in session_msgs:
            role = "bot" if m.get("sender_type") == "self" else "user"
            conversation.append({
                "role": role,
                "sender": m.get("sender", ""),
                "text": m.get("text", ""),
            })

        return {
            "draft_id": draft_id,
            "tick_id": tick_id,
            "timestamp": timestamp,
            "chat_name": tick_data.get("chat_name", ""),
            "status": "pending",
            "judge_result": judge_result,
            "conversation": conversation,
            "bot_reply": tick_data.get("bot_reply_text", "") or tick_data.get("reply_text", ""),
            "tool_calls": tick_data.get("tool_calls", []),
            "memory_injected": tick_data.get("memory_injected", "")[:2000],
            "full_system_prompt": tick_data.get("full_system_prompt", ""),
            "full_tools_context": tick_data.get("full_tools_context", ""),
            "full_user_prompt": tick_data.get("full_user_prompt", ""),
            "full_llm_messages": tick_data.get("full_llm_messages", []),
            "assets": {
                "screenshot_path": tick_data.get("screenshot_path", ""),
                "prompt_md_path": tick_data.get("prompt_md_path", ""),
                "tick_json_path": tick_data.get("tick_json_path", ""),
            },
            "generated_case": {},
            "review_history": [],
            "committed_at": None,
            "committed_by": None,
            "dismissed_at": None,
            "dismiss_reason": None,
        }

    # ------------------------------------------------------------------
    # 内部：自动入库判定
    # ------------------------------------------------------------------
    def _should_auto_commit(self, judge_result: dict) -> bool:
        return (
            judge_result.get("auto_commit") is True
            and judge_result.get("confidence", 0) >= AUTO_COMMIT_RULES["min_confidence"]
            and judge_result.get("badcase_type") in AUTO_COMMIT_RULES["allowed_types"]
        )

    # ------------------------------------------------------------------
    # 内部：自动入库
    # ------------------------------------------------------------------
    def _auto_commit(self, draft: dict):
        """直接追加到 benchmark 文件（经回归验证）"""
        module = draft["generated_case"].get("module", "P2")
        case_code = draft["generated_case"].get("case_code", "")
        if not case_code:
            _logger.warning("Auto commit skipped: no case code generated")
            return

        # 回归验证：确保不破坏现有 benchmark
        benchmark_file = self._get_benchmark_file(module)
        ok, reason = self._regression_check(benchmark_file, case_code)
        if not ok:
            _logger.warning("[Judge] 回归验证失败: %s，转为 pending", reason)
            draft["status"] = "pending"
            self._save_pending(draft)
            return

        # 追加到 benchmark 文件
        self._append_case_to_benchmark(benchmark_file, case_code)

        # 缓存 LLM 响应
        self._cache_auto_case(draft)

        # 记录到 committed
        draft["status"] = "committed"
        draft["committed_at"] = datetime.now().isoformat()
        draft["committed_by"] = "auto"
        self._write_json(self._committed_dir / f"{draft['draft_id']}.json", draft)

        _logger.info("Auto committed %s to %s", draft["draft_id"], benchmark_file.name)

    def _regression_check(self, benchmark_file: Path, case_code: str) -> tuple[bool, str]:
        """回归验证：确保追加 case 不会破坏现有 benchmark"""
        if not benchmark_file.exists():
            return False, "benchmark 文件不存在"

        content = benchmark_file.read_text(encoding="utf-8")

        # 1. 检查 case 不重复
        case_name = self._extract_case_name(case_code)
        if case_name and f'case_name="{case_name}"' in content:
            return False, f"case {case_name} 已存在"

        # 2. 语法验证 + import 回归验证
        test_content = content + f"\n\n{case_code}\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(test_content)
            tmp = f.name
        try:
            py_compile.compile(tmp, doraise=True)
            # 3. 回归验证：追加后模块能正常 import 且 BENCHMARK_CASES 可访问
            import importlib.util
            spec = importlib.util.spec_from_file_location("regression_test_module", tmp)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "BENCHMARK_CASES"):
                return False, "BENCHMARK_CASES 未找到"
        except py_compile.PyCompileError as e:
            return False, f"语法验证失败: {e}"
        except Exception as e:
            return False, f"回归验证失败: {e}"
        finally:
            os.unlink(tmp)

        return True, ""

    @staticmethod
    def _extract_case_name(case_code: str) -> str:
        m = re.search(r'case_name="([^"]+)"', case_code)
        return m.group(1) if m else ""

    def _get_benchmark_file(self, module: str) -> Path:
        mapping = {
            "P0": PROJECT_ROOT / "src" / "tests" / "test_tool_decision_benchmark.py",
            "P2": PROJECT_ROOT / "src" / "tests" / "test_reply_quality_benchmark.py",
            "P3": PROJECT_ROOT / "src" / "tests" / "test_reply_quality_benchmark.py",  # P3 先放 P2 里
        }
        return mapping.get(module, mapping["P2"])

    def _append_case_to_benchmark(self, benchmark_file: Path, case_code: str):
        """安全追加 case 到 benchmark 文件末尾"""
        if not benchmark_file.exists():
            _logger.warning("Benchmark file not found: %s", benchmark_file)
            return
        content = benchmark_file.read_text(encoding="utf-8")
        # 找到 BENCHMARK_CASES 列表的最后一个元素后面插入
        # 简单策略：在文件末尾追加（假设 case 是独立的 BenchmarkCase 定义）
        # 更好的策略：在 BENCHMARK_CASES = [ ... ] 的最后一个 case 后面插入
        insertion_marker = "# -------------------------------------------------------------------------\n# Auto-generated cases"
        if insertion_marker not in content:
            # 在文件末尾追加标记和新 case
            append_text = f"\n\n{insertion_marker}\n# -------------------------------------------------------------------------\n{case_code}\n"
            benchmark_file.write_text(content + append_text, encoding="utf-8")
        else:
            # 在已有标记后面追加
            parts = content.split(insertion_marker, 1)
            new_content = parts[0] + insertion_marker + "\n" + case_code + "\n" + parts[1]
            benchmark_file.write_text(new_content, encoding="utf-8")

    def _cache_auto_case(self, draft: dict):
        """缓存自动入库的 LLM 原始响应"""
        cache_path = self._auto_cases_dir / f"{draft['draft_id']}.json"
        self._write_json(cache_path, {
            "draft_id": draft["draft_id"],
            "judge_raw_response": draft.get("_judge_raw", ""),
            "timestamp": datetime.now().isoformat(),
        })

    # ------------------------------------------------------------------
    # 内部：pending / unjudged 保存
    # ------------------------------------------------------------------
    def _save_pending(self, draft: dict):
        path = self._pending_dir / f"{draft['draft_id']}.json"
        self._write_json(path, draft)

    def _save_unjudged(self, tick_data: dict, error: str):
        unjudged_dir = PROJECT_ROOT / "data" / "review_drafts" / "unjudged"
        unjudged_dir.mkdir(parents=True, exist_ok=True)
        tick_id = tick_data.get("tick_id", 0)
        path = unjudged_dir / f"tick_{tick_id}_unjudged.json"
        self._write_json(path, {"tick_data": tick_data, "error": error, "timestamp": datetime.now().isoformat()})

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _write_json(path: Path, data: dict):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
