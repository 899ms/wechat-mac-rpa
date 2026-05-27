#!/usr/bin/env python3
"""
A/B 实验 — 固定 Judge，变 Bot 参数，对比得分

用法:
    python3 scripts/run_experiment.py --exp time_awareness_off --all-labeled
    python3 scripts/run_experiment.py --exp reply_restraint_off --n-samples 10
"""

import json, os, sys, time, sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cases.db"
RESULTS_DIR = PROJECT_ROOT / "data" / "experiments"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Bot 参数配置
# =============================================================================

@dataclass
class BotConfig:
    """Bot 回复生成参数。"""
    name: str
    description: str = ""
    # Prompt 参数
    enable_time_awareness: bool = True
    enable_reply_restraint: bool = True
    enable_unread_dedup: bool = True
    enable_timestamps: bool = True
    # 工具参数
    enable_search_in_page: bool = True
    browse_truncate: int = 3000
    tool_result_truncate: int = 3000
    # 模型参数（可选切换）
    model: str = "deepseek-v4-flash"
    temperature: float = 0.7


# 基线 = 当前生产配置
CONTROL = BotConfig(name="control", description="当前生产配置（基线）")

# 实验组
BOT_EXPERIMENTS = {
    "no_time": BotConfig(
        name="no_time",
        description="关闭时间感知",
        enable_time_awareness=False, enable_timestamps=False,
    ),
    "no_restraint": BotConfig(
        name="no_restraint",
        description="关闭回复克制",
        enable_reply_restraint=False,
    ),
    "no_dedup": BotConfig(
        name="no_dedup",
        description="关闭未读去重",
        enable_unread_dedup=False,
    ),
    "no_search_page": BotConfig(
        name="no_search_page",
        description="关闭 search_in_page",
        enable_search_in_page=False,
    ),
    "short_truncate": BotConfig(
        name="short_truncate",
        description="browse 截断 1000 字",
        browse_truncate=1000, tool_result_truncate=500,
    ),
    "all_off": BotConfig(
        name="all_off",
        description="关闭所有 P0 改进（基线）",
        enable_time_awareness=False, enable_timestamps=False,
        enable_reply_restraint=False, enable_unread_dedup=False,
        enable_search_in_page=False, browse_truncate=1000, tool_result_truncate=500,
    ),
    # 增量实验：从 all_off 逐步开启功能
    "enable_time": BotConfig(
        name="enable_time",
        description="只开启时间感知",
        enable_time_awareness=True, enable_timestamps=True,
        enable_reply_restraint=False, enable_unread_dedup=False, enable_search_in_page=False,
    ),
    "enable_restraint": BotConfig(
        name="enable_restraint",
        description="只开启回复克制",
        enable_reply_restraint=True, enable_unread_dedup=True,
        enable_time_awareness=False, enable_timestamps=False, enable_search_in_page=False,
    ),
    "enable_search": BotConfig(
        name="enable_search",
        description="只开启 search_in_page",
        enable_search_in_page=True, browse_truncate=12000, tool_result_truncate=12000,
        enable_time_awareness=False, enable_timestamps=False,
        enable_reply_restraint=False, enable_unread_dedup=False,
    ),
    "enable_all_p0": BotConfig(
        name="enable_all_p0",
        description="开启所有 P0 功能",
        enable_time_awareness=True, enable_timestamps=True,
        enable_reply_restraint=True, enable_unread_dedup=True,
        enable_search_in_page=True, browse_truncate=12000, tool_result_truncate=12000,
    ),
}


# =============================================================================
# Bot 回复生成（用相同 prompt 调 LLM 重新生成）
# =============================================================================

def generate_reply(system_prompt: str, user_prompt: str, config: BotConfig) -> str:
    """根据 Bot 配置，用原始 prompt 调 LLM 生成回复。"""
    from src.utils.qwen_client import QwenClient

    # 按配置修改 prompt
    sp = system_prompt
    up = user_prompt

    if not config.enable_time_awareness:
        # 去掉时间上下文
        import re
        up = re.sub(r'当前时间：[^\n]+\n', '', up)
        up = re.sub(r'⚠️ 消息时间戳说明[^\n]*\n', '', up)
        up = re.sub(r'（[^）]*(?:分钟前|昨晚|今早|\d{2}:\d{2})[^）]*）', '', up)

    if not config.enable_reply_restraint:
        sp = sp.replace("### 7. 回复克制原则", "### 7. 回复克制原则（实验关闭）")
        sp = sp.replace("以下情况**不回复**", "以下情况可以回复")

    if not config.enable_unread_dedup:
        up = up.replace("⚠️(历史中已有回复，可跳过)", "")
        up = up.replace("提示：第", "提示（关闭）：第")

    if not config.enable_timestamps:
        up = re.sub(r'（[^）]*(?:分钟前|昨晚|今早|\d{2}:\d{2})[^）]*）', '', up)

    # 构建 messages
    messages = [{"role": "system", "content": sp[:8000]}]
    messages.append({"role": "user", "content": up[:12000]})

    try:
        client = QwenClient(model=config.model)
        raw = client.chat(messages=messages, temperature=config.temperature, max_tokens=500, timeout=30)
        text = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
        # 解析 JSON replies
        try:
            data = json.loads(text.strip().lstrip("```json").rstrip("```"))
            replies = data.get("replies", [])
            return " | ".join(replies) if replies else text[:200]
        except:
            return text[:200]
    except Exception as e:
        return f"[生成失败: {e}]"


# =============================================================================
# Judge（固定不变）
# =============================================================================

def judge_reply(tick_data: dict, bot_reply: str) -> dict:
    """用统一的 Judge 评分。"""
    from src.badcase.judge_worker import JudgeWorker
    import json as _json

    worker = JudgeWorker()
    tc = _json.loads(tick_data.get("tool_calls_json", "[]") or "[]")
    sp = tick_data.get("system_prompt", "") or ""
    up = tick_data.get("user_prompt", "") or ""
    llm_msgs = [{"role": "system", "content": sp}, {"role": "user", "content": up}]

    tool_info = [{"tool": t.get("tool_name",""), "args": str(t.get("arguments",""))[:200], "result": str(t.get("result_preview",""))[:3000]} for t in tc]

    return worker._judge({
        "tick_id": tick_data.get("tick_id", 0),
        "chat_name": tick_data.get("chat_name", ""),
        "bot_reply_text": bot_reply,
        "tool_calls": tc,
        "tool_results_json": _json.dumps(tool_info, ensure_ascii=False),
        "full_user_prompt": up,
        "full_system_prompt": sp,
        "full_llm_messages": llm_msgs,
    })


# =============================================================================
# Runner
# =============================================================================

def run_experiment(exp_config: BotConfig, tick_ids: list):
    """跑实验：对每个 tick，基线 vs 实验组都生成回复，Judge 打分，对比。"""
    from src.badcase.case_db import get_db

    control_results = []
    exp_results = []

    for tid in tick_ids:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM tick_log WHERE tick_id=? ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
        conn.close()
        if not r:
            continue
        d = dict(r)
        sp = d.get("system_prompt", "") or ""
        up = d.get("user_prompt", "") or ""

        # 对照组：用基线配置重新生成
        control_reply = generate_reply(sp, up, CONTROL)
        control_judge = judge_reply(d, control_reply)

        # 实验组：用实验配置重新生成
        exp_reply = generate_reply(sp, up, exp_config)
        exp_judge = judge_reply(d, exp_reply)

        control_results.append({"tick_id": tid, "reply": control_reply, "judge": control_judge})
        exp_results.append({"tick_id": tid, "reply": exp_reply, "judge": exp_judge})

        c_bc = "BAD" if control_judge.get("is_badcase") else "OK"
        e_bc = "BAD" if exp_judge.get("is_badcase") else "OK"
        c_s = control_judge.get("overall_score", 0)
        e_s = exp_judge.get("overall_score", 0)
        print(f"  #{tid}: baseline={c_bc}({c_s:.0f}) exp={e_bc}({e_s:.0f}) diff={e_s-c_s:+.0f}")

    n = len(control_results)
    c_bad = sum(1 for r in control_results if r["judge"].get("is_badcase"))
    e_bad = sum(1 for r in exp_results if r["judge"].get("is_badcase"))
    c_avg = sum(r["judge"].get("overall_score", 0) for r in control_results) / n if n else 0
    e_avg = sum(r["judge"].get("overall_score", 0) for r in exp_results) / n if n else 0

    print(f"\n基线: badcase={c_bad}/{n} ({c_bad/n*100:.0f}%) 均分={c_avg:.1f}")
    print(f"实验: badcase={e_bad}/{n} ({e_bad/n*100:.0f}%) 均分={e_avg:.1f}")
    print(f"差异: badcase {c_bad-e_bad:+d} 均分 {e_avg-c_avg:+.1f}")

    # 维度对比
    dims = ["幻觉控制", "时间推理", "回复必要性", "信息准确性", "上下文理解"]
    print("维度差异（实验-基线）:")
    for dim in dims:
        c_dim = sum(r["judge"].get("dimensions", {}).get(dim, {}).get("score", 0) for r in control_results) / n
        e_dim = sum(r["judge"].get("dimensions", {}).get(dim, {}).get("score", 0) for r in exp_results) / n
        diff = e_dim - c_dim
        bar = "█" * max(0, int(diff * 5)) if diff > 0 else "░" * max(0, int(abs(diff) * 5))
        print(f"  {dim}: {c_dim:.1f} → {e_dim:.1f} ({diff:+.1f}) {bar}")

    # 存入数据库
    db = get_db()
    conn = db._get_conn()
    conn.execute("""INSERT INTO experiments (name, description, n_samples,
        control_badcase_rate, exp_badcase_rate, control_avg_score, exp_avg_score,
        summary, dimension_diffs_json, is_improvement)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", (
        exp_config.name, exp_config.description, n,
        c_bad/n, e_bad/n, c_avg, e_avg,
        f"badcase {c_bad-e_bad:+d} 均分 {e_avg-c_avg:+.1f}",
        json.dumps({dim: round(
            sum(r["judge"].get("dimensions", {}).get(dim, {}).get("score", 0) for r in exp_results) / n -
            sum(r["judge"].get("dimensions", {}).get(dim, {}).get("score", 0) for r in control_results) / n, 1
        ) for dim in dims}, ensure_ascii=False),
        1 if e_avg > c_avg + 1 else 0,
    ))
    exp_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for c, e in zip(control_results, exp_results):
        for r, cfg in [(c, "control"), (e, exp_config.name)]:
            conn.execute("""INSERT OR REPLACE INTO experiment_results
                (experiment_id, tick_id, config_name, bot_reply,
                 judge_is_badcase, judge_score, judge_dimensions_json, judge_reason)
                VALUES (?,?,?,?,?,?,?,?)""", (
                exp_id, r["tick_id"], cfg, r["reply"][:500],
                1 if r["judge"].get("is_badcase") else 0,
                r["judge"].get("overall_score", 0),
                json.dumps(r["judge"].get("dimensions", {}), ensure_ascii=False),
                r["judge"].get("reason", ""),
            ))
    conn.commit(); conn.close()
    print(f"实验 ID={exp_id} 已保存")


# =============================================================================
# Main
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bot A/B 实验")
    parser.add_argument("--exp", required=True, help="实验名称: " + ", ".join(BOT_EXPERIMENTS.keys()))
    parser.add_argument("--tick-id", type=int, help="单个 tick ID")
    parser.add_argument("--all-labeled", action="store_true", help="所有人工标注的 tick")
    parser.add_argument("--n-samples", type=int, default=5, help="随机采样 N 个 tick")
    args = parser.parse_args()

    if args.exp not in BOT_EXPERIMENTS:
        print(f"未知实验: {args.exp}, 可用: {', '.join(BOT_EXPERIMENTS.keys())}")
        return

    exp_config = BOT_EXPERIMENTS[args.exp]

    if args.tick_id:
        tick_ids = [args.tick_id]
    elif args.all_labeled:
        conn = sqlite3.connect(str(DB_PATH))
        tick_ids = [r[0] for r in conn.execute("SELECT tick_id FROM tick_log WHERE human_is_badcase IS NOT NULL ORDER BY id").fetchall()]
        conn.close()
    else:
        conn = sqlite3.connect(str(DB_PATH))
        all_ids = [r[0] for r in conn.execute("SELECT tick_id FROM tick_log WHERE should_reply=1 ORDER BY RANDOM() LIMIT ?", (args.n_samples,)).fetchall()]
        conn.close()
        tick_ids = all_ids

    print(f"实验: {exp_config.name} — {exp_config.description}")
    print(f"样本: {len(tick_ids)} 个 tick, 固定 Judge: deepseek-v4-pro\n")

    run_experiment(exp_config, tick_ids)


if __name__ == "__main__":
    main()
