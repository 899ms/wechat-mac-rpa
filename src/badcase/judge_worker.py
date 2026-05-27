#!/usr/bin/env python3
"""JudgeWorker - 异步 badcase 判定，支持查证反思"""

import json, logging, os, queue, sqlite3, subprocess, threading, time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("src.badcase.judge_worker")

PROJECT_ROOT = Path(__file__).parent.parent.parent

from .case_generator import CaseGenerator
from .case_db import get_db


_JUDGE_PROMPT_TEMPLATE = """你是 Bot QA 审计员。逐项检查，每项独立判断。最后 is_badcase = 任意一项 issue=true。

## 时间锚点
当前时间: {current_time}。消息时间戳相对于此时间。

## Bot 本轮回复
{bot_reply}

## Bot 调用的工具及返回结果（事实来源，截断已放宽到 {tool_max} 字）
{tool_calls}

## Bot 看到的完整上下文（最近 {msg_max} 条消息，截断 {ctx_max} 字/条）
{full_messages}

## Bot 的系统提示词（行为规范）
{system_prompt}

## 5 项独立检查

### 检查1：幻觉
Bot 说了什么具体事实（人名/数字/事件/毕业院校/比分），在【工具返回】或【上下文】中能找到依据吗？
- 依据充足 → false
- 工具返回被截断看不到 → false（可能是截断问题，不能确定）
- search_memory 返回了相关信息但被截断 → false
- 完全没有依据 → true，detail 写"无依据事实：XXX"

### 检查2：时间误判
消息有时间标签吗？Bot 忽略了时间吗？Bot 说的"今天/现在"真的是今天/现在吗？
- 昨晚发的"好困" → Bot 说"通宵了" → true
- 凌晨/周末 → Bot 说"今天跌了X"（股市不开盘） → 调用 verify_tool 查当前时间
- 几小时前的消息 → Bot 当现在发的 → true
- 没有时间标签或正确理解 → false

### 检查3：过度回复 / 漏回复
用户最后一条需要回复吗？
- OK/好的/收到/嗯/纯表情/纯图片 → Bot 还回复了 → true（过度）
- Bot 在历史里已经回复过**这条完全相同的消息** → 又回了一遍 → true（过度）
- **用户发了新问题（不是已回复过的旧消息）→ Bot 空回复 → true（漏回复）**
- **用户反问（带问号/质疑语调）→ Bot 不回复 → true（漏回复）**
- 正常需要回且回了 → false
- 不需要回且没回 → false

### 检查4：信息不完整
工具返回有截断提示吗？Bot 把不完整信息当完整结论了？
- 工具返回提示"已截断" → Bot 断言了具体结论 → true
- 工具返回完整 → false

### 检查5：答非所问 / 话题混淆
用户问什么话题？Bot 答什么话题？一致吗？
- 用户问A，Bot 答无关的B → true（如用户问茅台，Bot 答拼多多）
- 用户纠正/质疑 Bot → Bot 没有调用工具查证而是随口回应 → true
- 回答切题 → false

### 检查6：格式问题（仅严重情况）
- Bot 把多条内容用换行符 `\n` 合并成一条长消息 → true（微信聊天不会这样换行，应该分多条发）
- 其他轻微格式差异 → false

## 人类 QA 的判断原则（从 12 个真实 badcase 中提炼，你必须遵守）

1. **时间语境**：消息没有时间戳时，不能假设是"现在"发的。Bot 推断"通宵了"、"今天开盘"等具体状态，必须有明确的时间依据。
2. **去重优先**：如果上下文中 Bot 已经回复过这条消息，再次回复就是过度回复。看历史比看未读更可靠。
3. **截断不完整**：工具返回被截断 ≠ 结论成立。Bot 不能说"根据搜索确定X"，只能说"搜索到了但不完整"。
4. **群聊指代**：追踪谁说了什么。@某人 的话是给那个人的。不要张冠李戴（把A做的事说成B做的）。
5. **克制回复**：OK/表情包/确认词不需要回。不是每条未读都要回复。
6. **前后一致**：Bot 前面夸自己不错，后面说自己傻 → 矛盾。自嘲不能推翻前面的自我评价。
7. **事实核查**：不要重复描述同一件事当新发现。不要说自己"刚查了"但没调用工具。
8. **被质疑应查证**：当用户纠正或质疑 Bot 的回答时，Bot 应该调用 search_memory/web_search 等工具验证，而不是随口回应或重复旧信息。不调工具直接回 → hallucination。
9. **反问必须回**：用户发了反问句或新问题，必须回复。历史中回复过类似话题不代表可以不回新问题。
10. **不要用换行符合并消息**：微信聊天中没人用 `\n` 换行写多条内容。多条内容应该分多条消息发。

## 人工标注参考
{human_fewshot}

## 输出（纯 JSON）
{{
  "checks": {{
    "幻觉": {{"issue": true/false, "detail": "证据"}},
    "时间误判": {{"issue": true/false, "detail": "证据"}},
    "过度回复": {{"issue": true/false, "detail": "证据"}},
    "信息不完整": {{"issue": true/false, "detail": "证据"}},
    "答非所问": {{"issue": true/false, "detail": "证据"}},
    "格式问题": {{"issue": true/false, "detail": "证据"}}
  }},
  "is_badcase": true/false,
  "badcase_type": "hallucination/time_misread/over_reply/info_incomplete/wrong_topic/bad_format/none",
  "confidence": 0.0~1.0,
  "reason": "出问题的检查项 + 证据",
  "expected_behavior": "应该怎么做",
  "verify_tool": {{"name": "search_memory", "query": "搜索词"}} 或 {{"name": "web_search", "query": "搜索词"}} 或 {{"name": "get_current_time", "query": ""}} 或 null
}}

is_badcase = 任意 check.issue == true

## 查证机制（verify_tool）
如果你怀疑 Bot 的某个回复是幻觉或编造，但工具返回结果似乎被截断（信息不足），**必须**设置 verify_tool 让系统查证。不要因为"不确定"就判 false。
- 当 Bot 说了具体的人名/数字/事件但你看不到依据 → 调用 search_memory 验证
- 当 Bot 回复"不知道"但你觉得搜索可能找到 → 调用 search_memory 验证
- 不要假设截断的信息里有依据，去验证它
- 当 Bot 说"今天未开盘"但你不知道是否真的未开盘 → 调用 get_current_time 或 web_search 验证
- 当 Bot 说了人名/数字但你从截断中看不到 → 调用 search_memory 验证
- verify_tool 设为 null 只有在你100%确定时才允许
"""


def _empty_judge_result(reason: str = "") -> dict:
    return {
        "is_badcase": False, "badcase_type": "none", "severity": "P2",
        "confidence": 0.0, "auto_commit": False, "overall_score": 0,
        "dimensions": {}, "reason": reason, "expected_behavior": "",
        "_verify_tool": None,
    }


def _get_qwen_client():
    from src.utils.qwen_client import QwenClient
    return QwenClient(model="deepseek-v4-pro")


class JudgeWorker:
    JUDGE_MAX_CONTEXT = 99999     # 不截断消息内容
    JUDGE_MAX_TOOL_RESULT = 99999 # 不截断工具结果
    JUDGE_MAX_MESSAGES = 99       # 全量消息

    def __init__(self, model: str = "deepseek-v4-pro", use_fewshot: bool = True):
        self.client = _get_qwen_client()
        self.queue: queue.Queue = queue.Queue()
        self._running = False
        self._consumer_thread: Optional[threading.Thread] = None
        self.case_generator = CaseGenerator()
        self.use_fewshot = use_fewshot
        self._pending_dir = PROJECT_ROOT / "data" / "review_drafts" / "pending"
        self._committed_dir = PROJECT_ROOT / "data" / "review_drafts" / "committed"
        self._dismissed_dir = PROJECT_ROOT / "data" / "review_drafts" / "dismissed"
        for d in [self._pending_dir, self._committed_dir, self._dismissed_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self._start_consumer()

    def _start_consumer(self):
        if self._running:
            return
        self._running = True
        self._consumer_thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._consumer_thread.start()

    def submit(self, tick_data: dict):
        self.queue.put(tick_data)

    def _consume_loop(self):
        while self._running:
            try:
                tick_data = self.queue.get(timeout=1)
                self._process_one(tick_data)
            except queue.Empty:
                continue
            except Exception as e:
                _logger.error("[Judge] consume error: %s", e)

    def _process_one(self, tick_data: dict):
        tick_id = tick_data.get("tick_id", 0)
        _logger.info("[Judge] processing tick %s", tick_id)
        judge_result = self._judge(tick_data)

        # 更新 tick_log
        try:
            import json as _json
            conn = get_db()._get_conn()
            conn.execute("""UPDATE tick_log SET judge_score=?, judge_is_badcase=?, judge_badcase_type=?,
                judge_dimensions_json=?, judge_reason=? WHERE tick_id=?""", (
                judge_result.get('overall_score', 0),
                1 if judge_result.get('is_badcase') else 0,
                judge_result.get('badcase_type', ''),
                _json.dumps(judge_result.get('dimensions', {}), ensure_ascii=False),
                judge_result.get('reason', ''),
                tick_id,
            ))
            conn.commit(); conn.close()
        except Exception:
            pass

        if not judge_result.get("is_badcase"):
            return
        draft = self._build_draft(tick_data, judge_result)
        generated = self.case_generator.generate(draft)
        draft["generated_case"] = generated
        if self._should_auto_commit(judge_result):
            self._auto_commit(draft)
        else:
            self._save_pending(draft)

    def _judge(self, tick_data: dict) -> dict:
        prompt = self._build_judge_prompt(tick_data)
        raw = self.client.chat(messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1200, timeout=60, response_format={"type": "json_object"})
        result = self._parse_judge_response(raw)

        # 查证反思（支持 search_memory / web_search / get_current_time）
        verify = result.get("_verify_tool")
        if verify and verify.get("name") and verify.get("query") is not None:
            tool_name = verify["name"]
            tool_query = (verify.get("query") or "").replace("'", "\\'")
            _logger.info("[Judge] 查证: %s(%s)", tool_name, tool_query)
            try:
                if tool_name == "search_memory":
                    r = subprocess.run(
                        ["python3", "-c", f"from src.memory.engine import MemoryEngine; m=MemoryEngine(); print(m.search_keyword('{tool_query}'))"],
                        capture_output=True, timeout=15, cwd=str(PROJECT_ROOT),
                    )
                    tool_result = r.stdout.decode("utf-8", errors="replace")[:5000] if r.returncode == 0 and r.stdout else "(empty)"
                elif tool_name == "web_search":
                    r = subprocess.run(
                        ["python3", "-c", f"from src.tools.builtin_tools import _web_search; print(_web_search(query='{tool_query}'))"],
                        capture_output=True, timeout=15, cwd=str(PROJECT_ROOT),
                    )
                    tool_result = r.stdout.decode("utf-8", errors="replace")[:3000] if r.returncode == 0 and r.stdout else "(empty)"
                elif tool_name == "get_current_time":
                    from datetime import datetime
                    tool_result = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
                else:
                    tool_result = f"未知工具: {tool_name}"

                verify_prompt = f"""查证结果（{tool_name}("{tool_query}")）：
{tool_result}

基于查证结果重新判断。如果结果支持 Bot 的回复 → is_badcase=false。输出格式同上。"""
                raw2 = self.client.chat(
                    messages=[{"role": "user", "content": prompt}, {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}, {"role": "user", "content": verify_prompt}],
                    temperature=0.1, max_tokens=1200, timeout=60, response_format={"type": "json_object"},
                )
                result = self._parse_judge_response(raw2)
            except Exception as e:
                _logger.warning("[Judge] 查证失败: %s", e)
        return result

    def _build_judge_prompt(self, tick_data: dict) -> str:
        sp = tick_data.get("full_system_prompt", "")
        llm_messages = tick_data.get("full_llm_messages", [])
        bot_reply = tick_data.get("bot_reply_text", "") or tick_data.get("reply_text", "")

        # 时间锚点：优先 tick 发生时间，fallback 当前
        tick_ts = tick_data.get("created_at", "")
        if tick_ts:
            try: now = datetime.fromisoformat(tick_ts)
            except: now = datetime.now()
        else:
            now = datetime.now()
        current_time = now.isoformat()

        tc = tick_data.get("tool_calls", [])
        if not tc:
            trace = tick_data.get("reply_generation_trace", [])
            for t in trace:
                if t.get("type") == "llm_response":
                    tc2 = t.get("tool_calls", [])
                    if tc2: tc = tc2; break

        tool_results_raw = tick_data.get("tool_results_json", "")
        if tool_results_raw:
            try:
                tc_with_results = json.loads(tool_results_raw)
                for x in tc_with_results:
                    if isinstance(x.get("result"), str) and len(x["result"]) > self.JUDGE_MAX_TOOL_RESULT:
                        x["result"] = x["result"][:self.JUDGE_MAX_TOOL_RESULT] + "..."
            except Exception:
                tc_with_results = tc
        else:
            tc_with_results = tc
        tool_calls_text = json.dumps(tc_with_results, ensure_ascii=False, indent=2)

        truncated = []
        for m in (llm_messages or [])[-self.JUDGE_MAX_MESSAGES:]:
            cm = dict(m)
            if isinstance(cm.get("content"), str) and len(cm["content"]) > self.JUDGE_MAX_CONTEXT:
                cm["content"] = cm["content"][:self.JUDGE_MAX_CONTEXT] + "..."
            if "tool_calls" in cm and cm["tool_calls"]:
                cm["tool_calls"] = [{"id": x.get("id"), "name": x.get("function", {}).get("name", "?")} for x in cm["tool_calls"]]
            truncated.append(cm)
        msgs_text = json.dumps(truncated, ensure_ascii=False, indent=2) if truncated else "(无)"

        # 注入人工标注的 few-shot（从 tick_log 读取最近的人工标注 case）
        human_shots = self._load_human_fewshot() if self.use_fewshot else ""

        return _JUDGE_PROMPT_TEMPLATE.format(
            current_time=current_time,
            tool_max=self.JUDGE_MAX_TOOL_RESULT, msg_max=self.JUDGE_MAX_MESSAGES, ctx_max=self.JUDGE_MAX_CONTEXT,
            system_prompt=sp, full_messages=msgs_text, tool_calls=tool_calls_text, bot_reply=bot_reply,
            human_fewshot=human_shots,
        )

    def _load_human_fewshot(self) -> str:
        """加载人工标注的 few-shot 示例。"""
        try:
            conn = get_db()._get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT tick_id, chat_name, replies_sent_json, human_notes, human_badcase_type "
                "FROM tick_log WHERE human_is_badcase=1 ORDER BY id DESC LIMIT 5"
            ).fetchall()
            conn.close()
            if not rows:
                return ""
            shots = []
            for r in rows:
                d = dict(r)
                notes = (d.get("human_notes") or "").strip()
                btype = (d.get("human_badcase_type") or "").strip()
                if not notes: continue
                # 提取判定逻辑而非列举案例
                logic = notes[:120]
                shots.append(f"人类判定为 {btype}：{logic}")
            if not shots: return ""
            return "人类 QA 判定过以下 badcase，学习他们的判断思路：\n" + "\n".join(f"- {s}" for s in shots)
        except Exception:
            return ""

    def _parse_judge_response(self, raw: str) -> dict:
        if not raw: return _empty_judge_result("空返回")
        text = raw.strip()
        if text.startswith("```json"): text = text[7:]
        if text.startswith("```"): text = text[3:]
        if text.endswith("```"): text = text[:-3]
        text = text.strip()
        s = text.find("{"); e = text.rfind("}")
        if s != -1 and e != -1 and e > s: text = text[s:e+1]
        try: data = json.loads(text)
        except json.JSONDecodeError: return _empty_judge_result("JSON 解析失败")

        checks = data.get("checks", {})
        issues = data.get("issues", [])
        dims_raw = data.get("dimensions", {})

        if checks:
            dims = {
                "幻觉控制": {"score": 1 if checks.get("幻觉",{}).get("issue") else 5, "comment": checks.get("幻觉",{}).get("detail","")},
                "记忆召回": {"score": 4, "comment": ""},
                "时间推理": {"score": 1 if checks.get("时间误判",{}).get("issue") else 5, "comment": checks.get("时间误判",{}).get("detail","")},
                "回复必要性": {"score": 1 if checks.get("过度回复",{}).get("issue") else 5, "comment": checks.get("过度回复",{}).get("detail","")},
                "信息准确性": {"score": 1 if checks.get("信息不完整",{}).get("issue") else 5, "comment": checks.get("信息不完整",{}).get("detail","")},
                "幽默感": {"score": 4, "comment": ""}, "逼格语气": {"score": 4, "comment": ""},
                "个性一致性": {"score": 4, "comment": ""}, "简洁度": {"score": 4, "comment": ""},
                "上下文理解": {"score": 1 if checks.get("答非所问",{}).get("issue") else 5, "comment": checks.get("答非所问",{}).get("detail","")},
                "简洁度": {"score": 1 if checks.get("格式问题",{}).get("issue") else 4, "comment": checks.get("格式问题",{}).get("detail","")},
            }
            overall_score = sum(d["score"] for d in dims.values())
        elif dims_raw:
            dims = {}
            for name in ["幻觉控制","记忆召回","时间推理","回复必要性","信息准确性","幽默感","逼格语气","个性一致性","简洁度","上下文理解"]:
                d = dims_raw.get(name, {})
                dims[name] = {"score": int(d.get("score",3)), "comment": d.get("comment","")}
            overall_score = int(data.get("overall_score", 0)) or sum(d["score"] for d in dims.values())
        elif issues:
            dims = {}
            for name, keywords in [("幻觉控制",["幻觉","编造","依据"]), ("时间推理",["时间","昨晚","通宵","刚刚"]), ("回复必要性",["过度","不必","多余","OK","表情"]), ("信息准确性",["截断","误解","工具"]), ("个性一致性",["矛盾","不一致"])]:
                dims[name] = {"score": 1 if any(any(kw in i for kw in keywords) for i in issues) else 5, "comment": ""}
            for name in ["记忆召回","幽默感","逼格语气","简洁度","上下文理解"]:
                dims[name] = {"score": 4, "comment": ""}
            overall_score = sum(d["score"] for d in dims.values())
        else:
            # q1-q6 fallback
            dims = {}
            for name, key in [("幻觉控制","q1_hallucination"), ("时间推理","q2_time_reasoning"), ("回复必要性","q3_reply_necessity"), ("信息准确性","q4_info_accuracy"), ("个性一致性","q6_persona")]:
                q = data.get(key, {})
                dims[name] = {"score": 1 if q.get("found") or q.get("found_issue") else 5, "comment": q.get("detail","")}
            for name in ["记忆召回","幽默感","逼格语气","简洁度","上下文理解"]:
                dims[name] = {"score": 4, "comment": ""}
            overall_score = sum(d["score"] for d in dims.values())

        return {
            "is_badcase": bool(data.get("is_badcase")),
            "badcase_type": data.get("badcase_type", "none"),
            "severity": data.get("severity", "P2"),
            "confidence": float(data.get("confidence", 0.0)),
            "auto_commit": bool(data.get("auto_commit")),
            "overall_score": overall_score,
            "dimensions": dims,
            "reason": data.get("reason", ""),
            "expected_behavior": data.get("expected_behavior", ""),
            "_verify_tool": data.get("verify_tool"),
        }

    def _build_draft(self, tick_data: dict, judge_result: dict) -> dict:
        return {
            "draft_id": f"tick_{tick_data.get('tick_id',0)}_{datetime.now().isoformat()}",
            "tick_id": tick_data.get("tick_id", 0),
            "timestamp": datetime.now().isoformat(),
            "chat_name": tick_data.get("chat_name", ""),
            "status": "pending",
            "judge_result": judge_result,
            "conversation": tick_data.get("session_input_messages", []),
            "bot_reply": tick_data.get("bot_reply_text", ""),
            "tool_calls": tick_data.get("tool_calls", []),
            "full_system_prompt": tick_data.get("full_system_prompt", ""),
            "full_user_prompt": tick_data.get("full_user_prompt", ""),
            "full_tools_context": tick_data.get("full_tools_context", ""),
            "full_llm_messages": tick_data.get("full_llm_messages", []),
        }

    def _should_auto_commit(self, judge_result: dict) -> bool:
        if not judge_result.get("is_badcase"): return False
        confidence = judge_result.get("confidence", 0)
        is_p0 = judge_result.get("severity") == "P0"
        auto = judge_result.get("auto_commit", False)
        allowed = {"missing_tool_call","redundant_tool_call","hallucination","wrong_fact","time_misread","over_reply","info_incomplete"}
        bt = judge_result.get("badcase_type","")
        return auto and confidence >= 0.9 and (is_p0 or bt in allowed)

    def _auto_commit(self, draft: dict):
        draft["status"] = "committed"
        draft["committed_at"] = datetime.now().isoformat()
        path = self._committed_dir / f"{draft['draft_id']}.json"
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_pending(self, draft: dict):
        path = self._pending_dir / f"{draft['draft_id']}.json"
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
