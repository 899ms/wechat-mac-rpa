#!/usr/bin/env python3
"""
Case Database — SQLite 存储所有 badcase 的完整信息（原始 prompt、对话、评分、工具调用）

替代原有的 JSON 文件散落存储，提供统一查询和趋势分析。

用法:
    from src.badcase.case_db import CaseDB
    db = CaseDB()
    db.insert_case(draft_dict)         # 入库一个 case
    cases = db.query_recent(days=7)    # 查询最近 7 天的 case
    db.export_daily_metrics(date)      # 导出某天的指标快照
"""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cases.db"


# =============================================================================
# Schema
# =============================================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT UNIQUE NOT NULL,
    tick_id INTEGER,
    chat_name TEXT,
    source TEXT,                    -- 'committed' | 'pending' | 'dismissed'
    status TEXT DEFAULT 'pending',  -- pending | committed | dismissed
    badcase_type TEXT,
    severity TEXT,                  -- P0 | P1 | P2
    confidence REAL,
    overall_score REAL,
    is_badcase INTEGER DEFAULT 0,
    auto_commit INTEGER DEFAULT 0,
    judge_reason TEXT,
    expected_behavior TEXT,
    screenshot_path TEXT,
    committed_at TEXT,
    committed_by TEXT,              -- 'auto' | 'manual'
    dismissed_at TEXT,
    dismiss_reason TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    git_commit TEXT
);

CREATE TABLE IF NOT EXISTS case_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    turn_order INTEGER,
    role TEXT,                      -- 'user' | 'bot'
    sender TEXT,
    text TEXT,
    UNIQUE(case_id, turn_order)
);

CREATE TABLE IF NOT EXISTS case_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL UNIQUE REFERENCES cases(id),
    system_prompt TEXT,
    user_prompt TEXT,
    tools_context TEXT,
    memory_injected TEXT
);

CREATE TABLE IF NOT EXISTS case_tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    call_order INTEGER,
    tool_name TEXT,
    arguments TEXT,
    result_preview TEXT             -- 截断到 500 字
);

CREATE TABLE IF NOT EXISTS case_dimensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    dimension_name TEXT,           -- 幻觉控制 | 记忆召回 | 幽默感 | ...
    score REAL,
    comment TEXT,
    UNIQUE(case_id, dimension_name)
);

CREATE TABLE IF NOT EXISTS case_llm_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    message_order INTEGER,
    role TEXT,
    content_preview TEXT            -- 截断到 1000 字
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    benchmark_name TEXT NOT NULL,   -- tool_decision | reply_quality | judge_quality | ...
    metric_name TEXT NOT NULL,      -- accuracy | precision | recall | f1 | pass_rate | ...
    metric_value REAL NOT NULL,
    git_commit TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(date, benchmark_name, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(created_at);
CREATE INDEX IF NOT EXISTS idx_cases_badcase_type ON cases(badcase_type);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_date ON daily_metrics(date);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_benchmark ON daily_metrics(benchmark_name, date);

-- ===== Benchmark case tables（P0/P2/P4 测试场景） =====

CREATE TABLE IF NOT EXISTS benchmark_tool_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_name TEXT UNIQUE NOT NULL,
    user_message TEXT NOT NULL,
    should_call_memory INTEGER NOT NULL DEFAULT 0,  -- 1=应调用, 0=不应调用
    category TEXT NOT NULL,                          -- person_identity | relationship | adversarial | ...
    notes TEXT,
    evaluation_mode TEXT DEFAULT 'binary',           -- binary | rubric
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS benchmark_reply_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_name TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    is_group INTEGER DEFAULT 0,
    unreplied_json TEXT NOT NULL,        -- JSON array of {sender, text}
    all_messages_json TEXT NOT NULL,     -- JSON array of {sender, text, sender_type}
    required_keywords_json TEXT,         -- JSON array of strings
    required_hits INTEGER DEFAULT 1,
    forbidden_keywords_json TEXT,        -- JSON array of strings
    min_replies INTEGER DEFAULT 1,
    max_replies INTEGER DEFAULT 3,
    rubric_name TEXT,                    -- reference to rubric definition in code
    notes TEXT,
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS benchmark_search_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_name TEXT UNIQUE NOT NULL,
    query TEXT NOT NULL,
    expected_docs_json TEXT NOT NULL,         -- JSON array of expected doc names
    unexpected_docs_json TEXT,                -- JSON array of unexpected doc names
    required_fragments_json TEXT,             -- JSON array of required keyword fragments
    category TEXT NOT NULL,                   -- exact_name | alias | relationship | ...
    notes TEXT,
    enabled INTEGER DEFAULT 1
);
"""


# =============================================================================
# Database class
# =============================================================================

class CaseDB:
    """Badcase 数据库 — 线程安全的 SQLite 封装。"""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（调用方负责关闭）。"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            conn.close()

    # ── INSERT ──

    def insert_case(self, draft: dict) -> int:
        """插入一个完整 case（来自 JudgeWorker 的 draft）。返回 case_id。"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                draft_id = draft.get("draft_id", "")
                if not draft_id:
                    return 0

                judge = draft.get("judge_result", {})

                # Upsert cases
                # Extract screenshot path
                assets = draft.get("assets", {})
                screenshot = assets.get("screenshot_path", "") or draft.get("screenshot_path", "")

                conn.execute("""
                    INSERT INTO cases (draft_id, tick_id, chat_name, source, status,
                        badcase_type, severity, confidence, overall_score,
                        is_badcase, auto_commit, judge_reason, expected_behavior,
                        screenshot_path, committed_at, committed_by, dismissed_at, dismiss_reason,
                        created_at, git_commit)
                    VALUES (?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?)
                    ON CONFLICT(draft_id) DO UPDATE SET
                        status=excluded.status, severity=excluded.severity,
                        overall_score=excluded.overall_score,
                        screenshot_path=COALESCE(excluded.screenshot_path, cases.screenshot_path),
                        committed_at=excluded.committed_at, committed_by=excluded.committed_by,
                        dismissed_at=excluded.dismissed_at, dismiss_reason=excluded.dismiss_reason
                """, (
                    draft_id,
                    draft.get("tick_id"),
                    draft.get("chat_name", ""),
                    draft.get("source", "committed"),
                    draft.get("status", "pending"),
                    judge.get("badcase_type", ""),
                    judge.get("severity", ""),
                    judge.get("confidence", 0),
                    judge.get("overall_score", 0),
                    1 if judge.get("is_badcase") else 0,
                    1 if judge.get("auto_commit") else 0,
                    judge.get("reason", ""),
                    judge.get("expected_behavior", ""),
                    screenshot,
                    draft.get("committed_at"),
                    draft.get("committed_by"),
                    draft.get("dismissed_at"),
                    draft.get("dismiss_reason"),
                    draft.get("timestamp", datetime.now().isoformat()),
                    draft.get("git_commit", ""),
                ))
                conn.commit()

                # Get case_id
                row = conn.execute("SELECT id FROM cases WHERE draft_id = ?", (draft_id,)).fetchone()
                if not row:
                    conn.close()
                    return 0
                case_id = row[0]

                # Delete old sub-records
                for table in ("case_conversations", "case_dimensions", "case_tool_calls"):
                    conn.execute(f"DELETE FROM {table} WHERE case_id = ?", (case_id,))

                # Insert conversations
                conv = draft.get("conversation", [])
                for i, m in enumerate(conv):
                    conn.execute(
                        "INSERT OR REPLACE INTO case_conversations (case_id, turn_order, role, sender, text) VALUES (?, ?, ?, ?, ?)",
                        (case_id, i, m.get("role", "user"), m.get("sender", ""), m.get("text", "")[:5000])
                    )

                # Insert prompts
                sp = draft.get("full_system_prompt", "")
                up = draft.get("full_user_prompt", "")
                tc = draft.get("full_tools_context", "")
                mi = draft.get("memory_injected", "")
                if sp or up:
                    conn.execute(
                        "INSERT OR REPLACE INTO case_prompts (case_id, system_prompt, user_prompt, tools_context, memory_injected) VALUES (?, ?, ?, ?, ?)",
                        (case_id, sp[:30000], up[:30000], tc[:10000], mi[:10000])
                    )

                # Insert dimensions
                dims = judge.get("dimensions", {})
                for name, dd in dims.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO case_dimensions (case_id, dimension_name, score, comment) VALUES (?, ?, ?, ?)",
                        (case_id, name, dd.get("score", 0), dd.get("comment", "")[:1000])
                    )

                # Insert tool calls
                tool_calls = draft.get("tool_calls", [])
                for i, tc_item in enumerate(tool_calls):
                    fn = tc_item.get("function", {}) if isinstance(tc_item, dict) else {}
                    name = fn.get("name", "") if isinstance(fn, dict) else getattr(tc_item, "tool_name", "")
                    args = fn.get("arguments", "") if isinstance(fn, dict) else str(tc_item)
                    conn.execute(
                        "INSERT INTO case_tool_calls (case_id, call_order, tool_name, arguments) VALUES (?, ?, ?, ?)",
                        (case_id, i, name, str(args)[:2000])
                    )

                # Insert LLM messages
                llm_msgs = draft.get("full_llm_messages", [])
                for i, msg in enumerate(llm_msgs):
                    content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                    conn.execute(
                        "INSERT INTO case_llm_messages (case_id, message_order, role, content_preview) VALUES (?, ?, ?, ?)",
                        (case_id, i, msg.get("role", "") if isinstance(msg, dict) else "", str(content)[:3000])
                    )

                conn.commit()
                return case_id
            finally:
                conn.close()

    def update_status(self, draft_id: str, status: str, **kwargs):
        """更新 case 状态。"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                updates = ["status = ?"]
                params = [status]
                for k, v in kwargs.items():
                    if k in ("committed_at", "committed_by", "dismissed_at", "dismiss_reason", "severity", "overall_score"):
                        updates.append(f"{k} = ?")
                        params.append(v)
                params.append(draft_id)
                conn.execute(f"UPDATE cases SET {', '.join(updates)} WHERE draft_id = ?", params)
                conn.commit()
            finally:
                conn.close()

    # ── QUERY ──

    def query_recent(self, days: int = 7, status: str = None) -> list[dict]:
        """查询最近 N 天的 case。"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                sql = "SELECT * FROM cases WHERE created_at >= ?"
                params = [cutoff]
                if status:
                    sql += " AND status = ?"
                    params.append(status)
                sql += " ORDER BY created_at DESC"
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_case_detail(self, draft_id: str) -> dict | None:
        """获取一个 case 的完整详情（含对话、prompt、评分）。"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                case = conn.execute("SELECT * FROM cases WHERE draft_id = ?", (draft_id,)).fetchone()
                if not case:
                    return None
                result = dict(case)

                # Conversations
                convs = conn.execute(
                    "SELECT * FROM case_conversations WHERE case_id = ? ORDER BY turn_order", (result["id"],)
                ).fetchall()
                result["conversation"] = [dict(c) for c in convs]

                # Prompts
                prompts = conn.execute(
                    "SELECT * FROM case_prompts WHERE case_id = ?", (result["id"],)
                ).fetchone()
                result["prompts"] = dict(prompts) if prompts else {}

                # Dimensions
                dims = conn.execute(
                    "SELECT * FROM case_dimensions WHERE case_id = ?", (result["id"],)
                ).fetchall()
                result["dimensions"] = {d["dimension_name"]: {"score": d["score"], "comment": d["comment"]} for d in dims}

                # Tools
                tools = conn.execute(
                    "SELECT * FROM case_tool_calls WHERE case_id = ? ORDER BY call_order", (result["id"],)
                ).fetchall()
                result["tool_calls"] = [dict(t) for t in tools]

                return result
            finally:
                conn.close()

    def get_stats(self, days: int = 7) -> dict:
        """获取统计概览。"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                total = conn.execute("SELECT COUNT(*) FROM cases WHERE created_at >= ?", (cutoff,)).fetchone()[0]
                by_type = {}
                for row in conn.execute(
                    "SELECT badcase_type, COUNT(*) as cnt FROM cases WHERE created_at >= ? AND badcase_type != '' GROUP BY badcase_type", (cutoff,)
                ):
                    by_type[row[0]] = row[1]
                by_status = {}
                for row in conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM cases WHERE created_at >= ? GROUP BY status", (cutoff,)
                ):
                    by_status[row[0]] = row[1]
                avg_score_row = conn.execute(
                    "SELECT AVG(overall_score) FROM cases WHERE created_at >= ? AND overall_score > 0", (cutoff,)
                ).fetchone()
                return {
                    "total_cases": total,
                    "by_type": by_type,
                    "by_status": by_status,
                    "avg_score": round(avg_score_row[0], 1) if avg_score_row[0] else 0,
                }
            finally:
                conn.close()

    # ── METRICS ──

    def insert_daily_metrics(self, date: str, benchmarks: dict, git_commit: str = ""):
        """插入每日 benchmark 指标。"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                for bname, bdata in benchmarks.items():
                    if "error" in bdata:
                        continue
                    for key, val in bdata.items():
                        if isinstance(val, (int, float)) and key not in ("tp", "fp", "fn", "tn", "passed", "total", "skipped", "case_count"):
                            conn.execute(
                                "INSERT OR REPLACE INTO daily_metrics (date, benchmark_name, metric_name, metric_value, git_commit) VALUES (?, ?, ?, ?, ?)",
                                (date, bname, key, val, git_commit)
                            )
                conn.commit()
            finally:
                conn.close()

    def get_metric_trend(self, benchmark_name: str, metric_name: str, days: int = 30) -> list[dict]:
        """获取某个指标的历史趋势。"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                rows = conn.execute(
                    "SELECT date, metric_value FROM daily_metrics WHERE benchmark_name = ? AND metric_name = ? AND date >= ? ORDER BY date",
                    (benchmark_name, metric_name, cutoff)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ── MIGRATION ──

    def migrate_from_json(self, drafts_dir: str = None):
        """从 data/review_drafts/ 迁移已有的 JSON draft 到数据库。"""
        if drafts_dir is None:
            drafts_dir = PROJECT_ROOT / "data" / "review_drafts"

        for status_dir in ("committed", "pending", "dismissed"):
            d = Path(drafts_dir) / status_dir
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                if "mock" in f.name or "test" in f.name:
                    continue
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    data["status"] = status_dir
                    data["source"] = status_dir
                    if not data.get("draft_id"):
                        data["draft_id"] = f.stem
                    case_id = self.insert_case(data)
                    if case_id:
                        print(f"  ✓ {f.stem} → case #{case_id}")
                except Exception as e:
                    print(f"  ✗ {f.stem}: {e}")


# =============================================================================
# Singleton
# =============================================================================

_db_instance: Optional[CaseDB] = None


    def load_benchmark_cases(self, bench_type: str) -> list[dict]:
        """加载任意 benchmark 的 case。bench_type: 'tool' | 'reply' | 'search' """
        table_map = {
            "tool": "benchmark_tool_cases",
            "reply": "benchmark_reply_cases",
            "search": "benchmark_search_cases",
        }
        table = table_map.get(bench_type)
        if not table:
            return []
        conn = self._get_conn()
        try:
            rows = conn.execute(f"SELECT * FROM {table} WHERE enabled=1").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_db() -> CaseDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = CaseDB()
    return _db_instance
