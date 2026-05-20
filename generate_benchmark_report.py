#!/usr/bin/env python3
"""生成 benchmark HTML 报告"""

import sys, json, os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')

# =============================================================================
# 收集数据
# =============================================================================

def collect_p0():
    """P0 Tool 决策"""
    from src.tests.test_tool_decision_benchmark import BENCHMARK_CASES, run_benchmark, SYSTEM_PROMPT, TOOLS
    case_map = {c.case_name: c for c in BENCHMARK_CASES}
    results = run_benchmark(use_api=False)
    cases = []
    for r in results:
        bc = case_map.get(r.case_name)
        cases.append({
            "name": r.case_name,
            "category": r.category,
            "status": "PASS" if r.passed else "FAIL",
            "user_message": bc.user_message if bc else "",
            "expected_call": r.should_call,
            "expected": "调用 search_memory" if r.should_call else "不调用 search_memory",
            "actual": "调用 search_memory" if r.actually_called else "不调用 search_memory",
            "tools": ", ".join(r.called_tools) if r.called_tools else "无",
            "raw": r.raw_response_preview,
            "pass_rate": f"{r.pass_rate:.0%}",
            "n_runs": r.n_runs,
        })
    passed = sum(1 for c in cases if c["status"] == "PASS")
    return {"name": "P0 Tool 调用决策", "total": len(cases), "passed": passed,
            "accuracy": passed/len(cases) if cases else 0, "cases": cases}

def collect_p1():
    """P1 记忆搜索召回"""
    from src.tests.test_memory_search_benchmark import run_benchmark, MemoryEngine
    from src.utils.qwen_client import QwenClient
    import os
    results = run_benchmark()
    # 创建 memory engine 获取实际搜索结果
    if not os.environ.get("DASHSCOPE_API_KEY"):
        with open(".env") as f:
            for line in f:
                if line.startswith("DASHSCOPE_API_KEY="):
                    os.environ["DASHSCOPE_API_KEY"] = line.split("=",1)[1].strip()
                    break
    mem = MemoryEngine(llm_client=QwenClient(model="deepseek-v4-flash"))
    cases = []
    for r in results:
        search_result = mem.search_keyword(r.query, max_chars=2000)
        cases.append({
            "name": r.case_name,
            "category": r.category,
            "status": "PASS" if r.passed else "FAIL",
            "query": r.query,
            "expected": ", ".join(r.expected_docs),
            "unexpected": ", ".join(r.unexpected_docs) if hasattr(r, "unexpected_docs") else "",
            "search_result": search_result[:500] if search_result else "(空)",
            "precision": f"{r.precision:.0%}",
            "recall": f"{r.recall:.0%}",
            "fp": r.fp,
            "fn": r.fn,
            "notes": r.notes,
        })
    passed = sum(1 for c in cases if c["status"] == "PASS")
    return {"name": "P1 记忆搜索召回", "total": len(cases), "passed": passed,
            "accuracy": passed/len(cases) if cases else 0, "cases": cases}

def collect_p2():
    """P2 回复质量（LLM-as-a-Judge）"""
    from src.tests.test_reply_quality_benchmark import BENCHMARK_CASES, run_benchmark
    results = run_benchmark(use_api=False)
    cases = []
    for c in BENCHMARK_CASES:
        r = next((x for x in results if x.case_name == c.case_name), None)
        if not r:
            continue
        # 构建完整对话上下文
        context_lines = []
        for m in c.all_messages:
            sender = "🤖 Bot" if m.sender_type.value == "self" else f"👤 {m.sender}"
            text = m.text or "[图片/卡片]"
            if getattr(m, 'image_description', ''):
                text = f"[图片: {m.image_description}]"
            context_lines.append(f"{sender}: {text}")
        
        unreplied_text = c.unreplied[-1].text[:60] if c.unreplied and c.unreplied[-1].text else "[空/图片]"
        
        # 评估判定详情
        judgement = []
        if r.reply_count_ok:
            judgement.append(f"✅ 回复数 {r.reply_count} 在范围 [{c.min_replies}, {c.max_replies}]")
        else:
            judgement.append(f"❌ 回复数 {r.reply_count} 不在范围 [{c.min_replies}, {c.max_replies}]")
        
        # Rubric 评估详情
        if r.rubric_scores and not r.rubric_scores.get("error"):
            judgement.append(f"🧑‍⚖️ 评估模式: {r.evaluation_mode}")
            for d in r.rubric_scores.get("dimensions", []):
                icon = "✅" if d["score"] == "PASS" else "❌"
                req = "(必须)" if d.get("required", True) else "(参考)"
                judgement.append(f"{icon} {d['name']} {req}: {d['reason']}")
            if r.rubric_scores.get("explanation"):
                judgement.append(f"💡 总结: {r.rubric_scores['explanation']}")
        else:
            # fallback keywords
            if c.required_hits == 0 or (c.required_keywords and len(c.required_keywords) - len(r.missing_keywords) >= c.required_hits):
                hits = len(c.required_keywords) - len(r.missing_keywords)
                judgement.append(f"✅ required_keywords 命中 {hits}/{len(c.required_keywords)} (需≥{c.required_hits})")
            else:
                judgement.append(f"❌ required_keywords 缺: {r.missing_keywords}")
            
            if r.found_forbidden:
                judgement.append(f"❌ forbidden_keywords 命中: {r.found_forbidden}")
            else:
                judgement.append(f"✅ forbidden_keywords 未命中")
            
            if r.rubric_scores and r.rubric_scores.get("error"):
                judgement.append(f"⚠️ Judge 错误: {r.rubric_scores['error'][:100]}")
        
        cases.append({
            "name": c.case_name,
            "category": c.category,
            "status": "PASS" if r.passed else "FAIL",
            "is_audit": bool(c.actual_replies),
            "context": "\n".join(context_lines),
            "unreplied": unreplied_text,
            "replies": r.replies,
            "required": c.required_keywords,
            "forbidden": c.forbidden_keywords,
            "required_hits": c.required_hits,
            "missing": r.missing_keywords,
            "found_forbidden": r.found_forbidden,
            "reply_count": r.reply_count,
            "reply_count_ok": r.reply_count_ok,
            "judgement": judgement,
            "notes": c.notes,
            "evaluation_mode": r.evaluation_mode,
            "rubric_scores": r.rubric_scores,
        })
    passed = sum(1 for c in cases if c["status"] == "PASS")
    return {"name": "P2 回复质量", "total": len(cases), "passed": passed,
            "accuracy": passed/len(cases) if cases else 0, "cases": cases}

def collect_unread():
    """未读角标识别"""
    fixture_dir = Path("src/tests/fixtures/unread_badge")
    if not fixture_dir.exists():
        return None
    cases = []
    for d in sorted(fixture_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("case_"):
            continue
        gt_file = d / "ground_truth.json"
        if not gt_file.exists():
            continue
        gt = json.loads(gt_file.read_text())
        cases.append({
            "name": d.name,
            "category": gt.get("category", ""),
            "status": "TODO",
            "target": gt.get("target_nickname", ""),
            "has_unread": gt.get("has_unread", False),
            "unread_count": gt.get("unread_count", ""),
            "avatar_type": gt.get("avatar_type", ""),
            "notes": gt.get("notes", ""),
        })
    return {"name": "未读角标识别", "total": len(cases), "passed": 0,
            "accuracy": 0, "cases": cases}

# =============================================================================
# HTML 模板
# =============================================================================

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WeChat Bot Benchmark 报告</title>
<style>
:root{{ --bg:#0d1117; --card:#161b22; --border:#30363d; --text:#c9d1d9; --muted:#8b949e; --green:#3fb950; --red:#f85149; --yellow:#d29922; --blue:#58a6ff; --purple:#bc8cff; }}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:20px}}
.header{{text-align:center;margin-bottom:30px}}
.header h1{{font-size:28px;margin-bottom:8px}}
.header .time{{color:var(--muted);font-size:14px}}

.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:30px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;transition:transform .2s}}
.card:hover{{transform:translateY(-2px)}}
.card h2{{font-size:16px;color:var(--muted);margin-bottom:12px;text-transform:uppercase;letter-spacing:1px}}
.card .metric{{font-size:36px;font-weight:700;margin-bottom:4px}}
.card .metric.green{{color:var(--green)}}
.card .metric.red{{color:var(--red)}}
.card .metric.yellow{{color:var(--yellow)}}
.card .detail{{color:var(--muted);font-size:14px}}
.card .bar{{height:6px;background:var(--border);border-radius:3px;margin-top:12px;overflow:hidden}}
.card .bar-inner{{height:100%;border-radius:3px;transition:width .5s}}
.card .bar-inner.green{{background:var(--green)}}
.card .bar-inner.red{{background:var(--red)}}
.card .bar-inner.yellow{{background:var(--yellow)}}

.filters{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;align-items:center}}
.filters label{{color:var(--muted);font-size:14px}}
.filters select,.filters input{{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:14px}}
.filters button{{background:var(--blue);color:#fff;border:none;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:14px}}
.filters button:hover{{opacity:.9}}

.module-section{{margin-bottom:40px}}
.module-header{{display:flex;align-items:center;gap:12px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border)}}
.module-header h2{{font-size:20px}}
.module-header .badge{{font-size:12px;padding:2px 8px;border-radius:12px;background:var(--border);color:var(--muted)}}
.module-header .badge.green{{background:rgba(63,185,80,.2);color:var(--green)}}
.module-header .badge.red{{background:rgba(248,81,73,.2);color:var(--red)}}

.case-list{{display:grid;gap:8px}}
.case-item{{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden}}
.case-item.collapsed .case-body{{display:none}}
.case-header{{display:flex;align-items:center;gap:12px;padding:12px 16px;cursor:pointer;user-select:none}}
.case-header:hover{{background:rgba(255,255,255,.03)}}
.case-status{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.case-status.pass{{background:var(--green)}}
.case-status.fail{{background:var(--red)}}
.case-name{{font-weight:600;font-size:14px;flex:1}}
.case-category{{font-size:12px;color:var(--muted);background:var(--border);padding:2px 8px;border-radius:4px}}
.case-toggle{{color:var(--muted);font-size:12px;transition:transform .2s}}
.case-item.collapsed .case-toggle{{transform:rotate(-90deg)}}
.case-body{{padding:0 16px 16px;border-top:1px solid var(--border)}}
.case-field{{display:flex;gap:8px;margin-top:8px;font-size:13px}}
.case-field .label{{color:var(--muted);min-width:70px;flex-shrink:0}}
.case-field .value{{color:var(--text);word-break:break-all}}
.case-field .value.code{{font-family:monospace;background:rgba(255,255,255,.05);padding:2px 6px;border-radius:4px}}
.case-field .value.green{{color:var(--green)}}
.case-field .value.red{{color:var(--red)}}
.case-reply{{background:rgba(255,255,255,.03);border-radius:6px;padding:10px 12px;margin-top:8px;font-size:13px}}
.case-reply .reply-label{{color:var(--muted);font-size:11px;margin-bottom:4px;text-transform:uppercase}}
.case-reply .reply-text{{color:var(--text);line-height:1.5}}
.case-section-title{{color:var(--blue);font-size:12px;font-weight:600;margin-top:16px;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}}
.case-block{{background:rgba(255,255,255,.03);border-radius:6px;padding:10px 12px;font-size:13px;line-height:1.6;white-space:pre-wrap;max-height:250px;overflow:auto}}
.judgement-box{{background:rgba(88,166,255,.08);border:1px solid rgba(88,166,255,.2);border-radius:6px;padding:10px 12px;margin-top:10px}}
.judgement-line{{font-size:12px;line-height:1.8}}

.footer{{text-align:center;color:var(--muted);font-size:12px;margin-top:40px;padding-top:20px;border-top:1px solid var(--border)}}

.hidden{{display:none !important}}
</style>
</head>
<body>
<div class="header">
  <h1>🤖 WeChat Bot Benchmark 报告</h1>
  <div class="time">生成时间: {timestamp}</div>
</div>

<div class="summary">
  {summary_cards}
</div>

<div class="filters">
  <label>模块:</label>
  <select id="filter-module">
    <option value="all">全部</option>
    {module_options}
  </select>
  <label>状态:</label>
  <select id="filter-status">
    <option value="all">全部</option>
    <option value="PASS">通过</option>
    <option value="FAIL">失败</option>
  </select>
  <label>搜索:</label>
  <input type="text" id="filter-search" placeholder="case 名称或内容...">
  <button onclick="expandAll()">展开全部</button>
  <button onclick="collapseAll()">折叠全部</button>
</div>

{module_sections}

<div class="footer">
  WeChat Mac RPA Benchmark | 真实 LLM 驱动 | 冻结标准版
</div>

<script>
function toggleCase(el) {{
  el.closest('.case-item').classList.toggle('collapsed');
}}
function expandAll() {{
  document.querySelectorAll('.case-item').forEach(el => el.classList.remove('collapsed'));
}}
function collapseAll() {{
  document.querySelectorAll('.case-item').forEach(el => el.classList.add('collapsed'));
}}

document.getElementById('filter-module').addEventListener('change', filterCases);
document.getElementById('filter-status').addEventListener('change', filterCases);
document.getElementById('filter-search').addEventListener('input', filterCases);

function filterCases() {{
  const mod = document.getElementById('filter-module').value;
  const stat = document.getElementById('filter-status').value;
  const search = document.getElementById('filter-search').value.toLowerCase();

  document.querySelectorAll('.module-section').forEach(section => {{
    const moduleName = section.dataset.module;
    const showModule = mod === 'all' || moduleName === mod;
    let hasVisible = false;

    section.querySelectorAll('.case-item').forEach(item => {{
      const status = item.dataset.status;
      const text = item.innerText.toLowerCase();
      const showStatus = stat === 'all' || status === stat;
      const showSearch = !search || text.includes(search);
      const visible = showModule && showStatus && showSearch;
      item.classList.toggle('hidden', !visible);
      if (visible) hasVisible = true;
    }});

    section.classList.toggle('hidden', !hasVisible);
  }});
}}

// 默认折叠
window.addEventListener('DOMContentLoaded', () => {{
  document.querySelectorAll('.case-item').forEach(el => el.classList.add('collapsed'));
}});
</script>
</body>
</html>
'''

def render_summary_card(m):
    acc = m["accuracy"]
    color = "green" if acc >= 0.9 else "yellow" if acc >= 0.7 else "red"
    pct = f"{acc:.1%}"
    return f'''<div class="card">
  <h2>{m["name"]}</h2>
  <div class="metric {color}">{pct}</div>
  <div class="detail">{m["passed"]}/{m["total"]} 通过</div>
  <div class="bar"><div class="bar-inner {color}" style="width:{pct}"></div></div>
</div>'''

def render_p0_case(c):
    color = "green" if c["status"] == "PASS" else "red"
    match_icon = "✅" if c["status"] == "PASS" else "❌"
    return f'''<div class="case-item collapsed" data-status="{c["status"]}">
  <div class="case-header" onclick="toggleCase(this)">
    <div class="case-status {color}"></div>
    <div class="case-name">{c["name"]}</div>
    <div class="case-category">{c["category"]}</div>
    <div class="case-toggle">▼</div>
  </div>
  <div class="case-body">
    <div class="case-field"><span class="label">判定:</span><span class="value {color}">{match_icon} {c["status"]}</span></div>
    <div class="case-section-title">📥 输入 (User Message)</div>
    <div class="case-block">{c["user_message"]}</div>
    <div class="case-section-title">📤 输出 (LLM 响应)</div>
    <div class="case-field"><span class="label">原始响应:</span><span class="value code">{c["raw"]}</span></div>
    <div class="case-field"><span class="label">调用工具:</span><span class="value code">{c["tools"]}</span></div>
    <div class="case-section-title">🎯 期望 vs 实际</div>
    <div class="case-field"><span class="label">期望:</span><span class="value">{c["expected"]}</span></div>
    <div class="case-field"><span class="label">实际:</span><span class="value">{c["actual"]}</span></div>
    <div class="case-field"><span class="label">稳定性:</span><span class="value">{c["pass_rate"]} ({c["n_runs"]} runs)</span></div>
  </div>
</div>'''

def render_p1_case(c):
    color = "green" if c["status"] == "PASS" else "red"
    match_icon = "✅" if c["status"] == "PASS" else "❌"
    return f'''<div class="case-item collapsed" data-status="{c["status"]}">
  <div class="case-header" onclick="toggleCase(this)">
    <div class="case-status {color}"></div>
    <div class="case-name">{c["name"]}</div>
    <div class="case-category">{c["category"]}</div>
    <div class="case-toggle">▼</div>
  </div>
  <div class="case-body">
    <div class="case-field"><span class="label">判定:</span><span class="value {color}">{match_icon} {c["status"]}</span></div>
    <div class="case-section-title">📥 输入 (Query)</div>
    <div class="case-block">{c["query"]}</div>
    <div class="case-section-title">📤 输出 (搜索结果)</div>
    <div class="case-block" style="font-size:12px;max-height:200px;overflow:auto;">{c["search_result"]}</div>
    <div class="case-section-title">🎯 期望 vs 实际</div>
    <div class="case-field"><span class="label">期望文档:</span><span class="value code">{c["expected"]}</span></div>
    <div class="case-field"><span class="label">不应出现:</span><span class="value code">{c["unexpected"]}</span></div>
    <div class="case-field"><span class="label">Precision:</span><span class="value {color}">{c["precision"]}</span></div>
    <div class="case-field"><span class="label">Recall:</span><span class="value {color}">{c["recall"]}</span></div>
    <div class="case-field"><span class="label">FP:</span><span class="value">{c["fp"]}</span></div>
    <div class="case-field"><span class="label">FN:</span><span class="value">{c["fn"]}</span></div>
    <div class="case-field"><span class="label">说明:</span><span class="value">{c["notes"]}</span></div>
  </div>
</div>'''

def render_p2_case(c):
    color = "green" if c["status"] == "PASS" else "red"
    audit_badge = " [审计]" if c["is_audit"] else ""
    
    # 判定详情
    judgement_html = ""
    for j in c["judgement"]:
        judgement_html += f'<div class="judgement-line">{j}</div>'
    
    # 回复
    replies_html = ""
    for i, r in enumerate(c["replies"], 1):
        replies_html += f'<div class="case-reply"><div class="reply-label">回复 {i}</div><div class="reply-text">{r}</div></div>'
    
    match_icon = "✅" if c["status"] == "PASS" else "❌"
    
    # Rubric 评估详情展示
    eval_mode = c.get("evaluation_mode", "keywords")
    rubric_scores = c.get("rubric_scores")
    
    if rubric_scores and not rubric_scores.get("error"):
        # 展示 Rubric 维度
        dims_html = ""
        for d in rubric_scores.get("dimensions", []):
            dim_color = "green" if d["score"] == "PASS" else "red"
            req_badge = "<span style='font-size:11px;color:var(--yellow)'>必须</span>" if d.get("required", True) else "<span style='font-size:11px;color:var(--muted)'>参考</span>"
            dims_html += f'''<div class="case-field" style="margin-top:6px">
        <span class="label" style="color:var(--{dim_color})">{d["score"]}</span>
        <span class="value"><strong>{d["name"]}</strong> {req_badge}<br/><span style="color:var(--muted);font-size:12px">{d.get("reason", "")}</span></span>
      </div>'''
        
        explanation = rubric_scores.get("explanation", "")
        exp_html = f'<div class="case-field" style="margin-top:8px"><span class="label">总结:</span><span class="value">{explanation}</span></div>' if explanation else ""
        
        eval_section = f'''<div class="case-field"><span class="label">评估模式:</span><span class="value code">🧑‍⚖️ {eval_mode}</span></div>
    <div style="background:rgba(188,140,255,.08);border:1px solid rgba(188,140,255,.2);border-radius:6px;padding:10px 12px;margin-top:10px">
      <div style="font-size:12px;color:var(--purple);font-weight:600;margin-bottom:6px">🧑‍⚖️ Rubric 维度评分</div>
      {dims_html}
      {exp_html}
    </div>'''
    else:
        # fallback: 展示 keywords
        missing = ", ".join(c["missing"]) if c["missing"] else "无"
        forbidden = ", ".join(c["found_forbidden"]) if c["found_forbidden"] else "无"
        error_msg = rubric_scores.get("error", "") if rubric_scores else ""
        error_html = f'<div class="case-field"><span class="label">Judge错误:</span><span class="value red">{error_msg[:100]}</span></div>' if error_msg else ""
        eval_section = f'''<div class="case-field"><span class="label">评估模式:</span><span class="value code">{eval_mode}</span></div>
    <div class="case-field"><span class="label">required:</span><span class="value code">{c["required"]} (需命中≥{c["required_hits"]})</span></div>
    <div class="case-field"><span class="label">forbidden:</span><span class="value code">{c["forbidden"]}</span></div>
    <div class="case-field"><span class="label">缺关键词:</span><span class="value red">{missing}</span></div>
    <div class="case-field"><span class="label">命中禁词:</span><span class="value red">{forbidden}</span></div>
    {error_html}'''
    
    return f'''<div class="case-item collapsed" data-status="{c["status"]}">
  <div class="case-header" onclick="toggleCase(this)">
    <div class="case-status {color}"></div>
    <div class="case-name">{c["name"]}{audit_badge}</div>
    <div class="case-category">{c["category"]}</div>
    <div class="case-toggle">▼</div>
  </div>
  <div class="case-body">
    <div class="case-field"><span class="label">判定:</span><span class="value {color}">{match_icon} {c["status"]}</span></div>
    
    <div class="case-section-title">📥 输入 (对话上下文)</div>
    <div class="case-block">{c["context"]}</div>
    
    <div class="case-section-title">📤 输出 (Bot 回复)</div>
    {replies_html}
    
    <div class="case-section-title">🎯 评估详情</div>
    {eval_section}
    <div class="judgement-box">
      {judgement_html}
    </div>
    <div class="case-field"><span class="label">说明:</span><span class="value">{c["notes"]}</span></div>
  </div>
</div>'''

def render_unread_case(c):
    return f'''<div class="case-item collapsed" data-status="{c["status"]}">
  <div class="case-header" onclick="toggleCase(this)">
    <div class="case-status" style="background:var(--yellow)"></div>
    <div class="case-name">{c["name"]}</div>
    <div class="case-category">{c["category"]}</div>
    <div class="case-toggle">▼</div>
  </div>
  <div class="case-body">
    <div class="case-field"><span class="label">目标:</span><span class="value">{c["target"]}</span></div>
    <div class="case-field"><span class="label">未读:</span><span class="value">{c["has_unread"]} ({c["unread_count"]})</span></div>
    <div class="case-field"><span class="label">头像类型:</span><span class="value">{c["avatar_type"]}</span></div>
    <div class="case-field"><span class="label">说明:</span><span class="value">{c["notes"]}</span></div>
  </div>
</div>'''

def main():
    print("收集 P0 数据...")
    p0 = collect_p0()
    print(f"  P0: {p0['passed']}/{p0['total']}")

    print("收集 P1 数据...")
    p1 = collect_p1()
    print(f"  P1: {p1['passed']}/{p1['total']}")

    print("收集 P2 数据...")
    p2 = collect_p2()
    print(f"  P2: {p2['passed']}/{p2['total']}")

    print("收集未读角标数据...")
    unread = collect_unread()
    if unread:
        print(f"  未读角标: {unread['total']} cases")
    else:
        print("  未读角标: 无 fixture")

    modules = [m for m in [p0, p1, p2, unread] if m]

    # Summary cards
    summary_cards = "\n".join(render_summary_card(m) for m in modules)

    # Module options
    module_options = "\n".join(f'<option value="{m["name"]}">{m["name"]}</option>' for m in modules)

    # Module sections
    sections = []
    for m in modules:
        if m["name"] == "P0 Tool 调用决策":
            cases_html = "\n".join(render_p0_case(c) for c in m["cases"])
        elif m["name"] == "P1 记忆搜索召回":
            cases_html = "\n".join(render_p1_case(c) for c in m["cases"])
        elif m["name"] == "P2 回复质量":
            cases_html = "\n".join(render_p2_case(c) for c in m["cases"])
        else:
            cases_html = "\n".join(render_unread_case(c) for c in m["cases"])

        acc_color = "green" if m["accuracy"] >= 0.9 else "yellow" if m["accuracy"] >= 0.7 else "red"
        badge = f'<span class="badge {acc_color}">{m["passed"]}/{m["total"]}</span>'

        sections.append(f'''<div class="module-section" data-module="{m["name"]}">
  <div class="module-header">
    <h2>{m["name"]}</h2>
    {badge}
  </div>
  <div class="case-list">
    {cases_html}
  </div>
</div>''')

    html = HTML_TEMPLATE.format(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary_cards=summary_cards,
        module_options=module_options,
        module_sections="\n".join(sections),
    )

    output = Path("benchmark_report.html")
    output.write_text(html, encoding="utf-8")
    print(f"\n✅ 报告已生成: {output.absolute()}")

if __name__ == "__main__":
    main()
