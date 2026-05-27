#!/usr/bin/env python3
"""wechat-twin Admin — 统一开发者后台"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json as _json
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from src.badcase.case_db import get_db

app = FastAPI(title="wechat-twin Admin")

HEADER = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>wechat-twin Admin</title>
<style>:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--green:#3fb950;--red:#f85149;--yellow:#d29922;--blue:#58a6ff}
*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:var(--bg);color:var(--text);padding:0;display:flex;min-height:100vh}
nav{width:200px;background:var(--card);border-right:1px solid var(--border);padding:16px 0;flex-shrink:0}
nav a{display:block;padding:8px 20px;color:var(--text);text-decoration:none;font-size:13px;transition:background .15s}
nav a:hover{background:rgba(255,255,255,.05)}nav a.active{color:var(--blue);background:rgba(88,166,255,.1)}
main{flex:1;padding:24px;overflow:auto}h1{font-size:20px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--border)}th{color:var(--muted);font-weight:600;font-size:11px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px}
.metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin:12px 0}
.metric{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;text-align:center}
.metric .value{font-size:28px;font-weight:700}.metric .label{font-size:11px;color:var(--muted);margin-top:4px}
/* Lightbox */
#lightbox{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.9);z-index:9999;cursor:zoom-out;align-items:center;justify-content:center}
#lightbox img{max-width:95vw;max-height:95vh;object-fit:contain}
#lightbox.show{display:flex}
</style></head><body>
<div id="lightbox" onclick="this.classList.remove('show')"><img id="lightbox-img" src=""></div>
<nav>
<div style="padding:12px 20px;font-weight:700;font-size:15px;margin-bottom:8px">wechat-twin</div>
<a href="/">📊 Dashboard</a>
<a href="/ticks">🔍 Tick 查看</a>
<a href="/gt">🏷️ GT 标注</a>
<a href="/review">🧑‍⚖️ 审核</a>
<a href="/screenshots">📸 截图OCR</a>
<a href="/benchmark/judge">📊 Judge质量</a>
<a href="/benchmark/reply">🤖 回复质量</a>
<a href="/experiments">🧪 实验</a>
</nav><main>"""

FOOTER = """</main>
<script>
document.addEventListener('dblclick',function(e){
  var img=e.target.closest('img');
  if(!img || img.id==='lightbox-img')return;
  var lb=document.getElementById('lightbox');
  document.getElementById('lightbox-img').src=img.src;
  lb.classList.add('show');
});
</script>
</body></html>"""

def _page(title: str, content: str, active: str = "") -> str:
    nav = HEADER
    for href, label in [("/", "📊 Dashboard"), ("/ticks", "🔍 Tick"), ("/gt", "🏷️ GT"), ("/review", "🧑‍⚖️ 审核"), ("/screenshots", "📸 截图OCR"), ("/benchmark/judge", "📊 Judge"), ("/benchmark/reply", "🤖 回复"), ("/experiments", "🧪 实验")]:
        cls = ' class="active"' if href == active else ""
        nav += f'<a href="{href}"{cls}>{label}</a>'
    nav += "</nav><main>"
    return nav + f"<h1>{title}</h1>" + content + FOOTER


@app.get("/", response_class=HTMLResponse)
def dashboard():
    db = get_db()
    today = __import__('datetime').datetime.now().strftime("%Y-%m-%d")
    conn = db._get_conn()
    total = conn.execute("SELECT COUNT(*) FROM tick_log WHERE date(created_at)=?", (today,)).fetchone()[0]
    replied = conn.execute("SELECT COUNT(*) FROM tick_log WHERE date(created_at)=? AND should_reply=1", (today,)).fetchone()[0]
    avg_score = conn.execute("SELECT ROUND(AVG(judge_score),1) FROM tick_log WHERE date(created_at)=? AND judge_score>0", (today,)).fetchone()[0] or 0
    skipped = conn.execute("SELECT COUNT(*) FROM tick_log WHERE date(created_at)=? AND skip_reason IS NOT NULL", (today,)).fetchone()[0]
    conn.close()

    content = f"""
    <div class="metrics">
      <div class="metric"><div class="value" style="color:var(--blue)">{total}</div><div class="label">今日 Tick</div></div>
      <div class="metric"><div class="value" style="color:var(--green)">{replied}</div><div class="label">回复数</div></div>
      <div class="metric"><div class="value" style="color:var(--purple)">{avg_score}</div><div class="label">平均 Judge 分</div></div>
      <div class="metric"><div class="value" style="color:var(--muted)">{skipped}</div><div class="label">跳过数</div></div>
      <div class="metric"><div class="value" style="color:var(--yellow)">{round(skipped*100/max(total,1))}%</div><div class="label">跳过率</div></div>
    </div>
    <p style="color:var(--muted);font-size:13px">数据来自 tick_log 表 · 刷新页面更新</p>"""
    return HTMLResponse(_page("Dashboard", content, "/"))


@app.get("/ticks", response_class=HTMLResponse)
def tick_list(page: int = Query(1), filter: str = Query("all")):
    db = get_db()
    conn = db._get_conn()
    offset = (page - 1) * 20
    where = "" if filter == "all" else f"WHERE skip_reason IS NOT NULL" if filter == "skipped" else f"WHERE should_reply=1" if filter == "replied" else ""
    rows = conn.execute(f"SELECT id, session_id, tick_id, chat_name, messages_count, new_messages_count, should_reply, skip_reason, judge_score, human_is_badcase, human_badcase_type, replies_sent_json, duration_ms, created_at FROM tick_log {where} ORDER BY created_at DESC, tick_id DESC LIMIT 20 OFFSET {offset}").fetchall()
    conn.close()

    rows_html = ""
    for r in rows:
        status = "⏭️跳过" if r["skip_reason"] else "✅回复" if r["should_reply"] else "⏭️无消息"
        llm_score = f'{r["judge_score"]:.0f}' if r['judge_score'] else "-"
        human = ""
        if r['human_is_badcase'] == 1:
            human = f'❌{r["human_badcase_type"] or "badcase"}'
        elif r['human_is_badcase'] == 0:
            human = "✅OK"
        reply_preview = ""
        rp = r['replies_sent_json']
        if rp and rp != '[]':
            try:
                import json as _j2
                arr = _j2.loads(rp)
                reply_preview = " | ".join(str(x)[:20] for x in (arr if isinstance(arr, list) else []))[:60]
            except: pass
        rows_html += f"""<tr>
          <td><a href="/ticks/{r['id']}" style="color:var(--blue)">{r['session_id']}:#{r['tick_id']}</a></td>
          <td>{r['chat_name'] or '-'}</td><td>{r['new_messages_count'] or r['messages_count'] or 0}条</td>
          <td>{status}</td><td style="font-size:11px">{reply_preview}</td><td>{llm_score}</td><td>{human}</td><td>{r['duration_ms'] or 0}ms</td>
          <td style="font-size:11px;color:var(--muted)">{r['created_at'][:16] if r['created_at'] else ''}</td></tr>"""

    conn = db._get_conn()
    total = conn.execute(f"SELECT COUNT(*) FROM tick_log {where}").fetchone()[0]
    conn.close()
    total_pages = (total + 19) // 20
    content = f"""<p style="margin-bottom:12px"><a href="?filter=all">全部({total})</a> | <a href="?filter=replied">已回复</a> | <a href="?filter=skipped">跳过</a> | <span style="color:var(--muted);font-size:12px">每页20条</span></p>
    <table><tr><th>Tick</th><th>聊天</th><th>消息</th><th>状态</th><th>回复</th><th>LLM</th><th>👤</th><th>耗时</th><th>时间</th></tr>{rows_html}</table>
    <div style="margin-top:12px;font-size:13px">
      <a href="?page={page-1}&filter={filter}" style="color:var(--blue);margin-right:12px" {'hidden' if page<=1 else ''}>← 上一页</a>
      第 {page} 页 / 共 {total_pages} 页
      <a href="?page={page+1}&filter={filter}" style="color:var(--blue);margin-left:12px">下一页 →</a>
    </div>"""
    return HTMLResponse(_page("Tick 查看", content, "/ticks"))


@app.get("/ticks/{id}", response_class=HTMLResponse)
def tick_detail(id: int):
    db = get_db()
    conn = db._get_conn()
    r = conn.execute("SELECT * FROM tick_log WHERE id=?", (id,)).fetchone()
    conn.close()
    if not r:
        return HTMLResponse("<h1>Tick not found</h1>")
    d = dict(r)
    replies = d.get("replies_sent_json", "[]") or "[]"
    # 格式化 Bot 回复
    try:
        import json as _j4
        reply_list = _j4.loads(replies) if replies else []
        replies_display = "<br>".join(f'<span style="background:rgba(88,166,255,.15);padding:2px 8px;border-radius:4px;margin:2px;display:inline-block;font-size:13px">{r}</span>' for r in reply_list) if reply_list else replies
    except:
        replies_display = replies
    sp = d.get("system_prompt") or ""
    up = d.get("user_prompt") or ""
    raw = d.get("raw_response") or ""
    tools = d.get("tool_calls_json") or "[]"
    tool_results = d.get("tool_results_json") or "[]"

    # 原有信息卡片
    ms = d.get("duration_ms",0) or 0
    status = d.get("skip_reason") or ("已回复" if d.get("should_reply") else "无消息")
    content = f"""
    <div class="card"><b>{d.get("session_id","")}:#{d["tick_id"]}</b> — {d.get("created_at","")[:16]}</div>
    <div class="card"><b>聊天:</b> {d.get("chat_name","?")} {"(群)" if d.get("is_group") else "(私)"} | <b>状态:</b> {status} | <b>耗时:</b> {ms}ms</div>
    <div class="card"><b>消息:</b> 总{d.get("messages_count",0)}条 新{d.get("new_messages_count",0)}条 | <b>发送:</b> {"OK" if d.get("send_success") else "N/A"}</div>
    <div class="card"><b>Bot 回复:</b><br>{replies_display}</div>
    <details style="margin-bottom:12px"><summary style="cursor:pointer;color:var(--blue)">System Prompt ({len(sp)}字)</summary><div class="card"><pre style="font-size:10px;max-height:300px;overflow:auto;white-space:pre-wrap">{sp}</pre></div></details>
    <details style="margin-bottom:12px"><summary style="cursor:pointer;color:var(--blue)">User Prompt ({len(up)}字)</summary><div class="card"><pre style="font-size:10px;max-height:400px;overflow:auto;white-space:pre-wrap">{up}</pre></div></details>
    <details style="margin-bottom:12px"><summary style="cursor:pointer;color:var(--muted)">Raw Response</summary><div class="card"><pre style="font-size:10px;max-height:200px;overflow:auto">{raw}</pre></div></details>
    """
    # 工具调用 + 结果（合并 tool_calls_json 和 tool_results_json）
    try:
        import json as _j3
        tc_list = _j3.loads(tools) if tools else []
        tr_list = _j3.loads(tool_results) if tool_results else []
        # 合并：优先用 tool_results_json 的完整结果，没有的话 fallback 到 result_preview
        all_tools = []
        seen = set()
        for tr in tr_list:
            name = tr.get("tool", "?")
            seen.add(name)
            all_tools.append({"tool_name": name, "arguments": tr.get("args", ""), "result_preview": tr.get("result", "")})
        for t in tc_list:
            name = t.get('tool_name', '?')
            if name not in seen:
                all_tools.append(t)  # 保持原始 result_preview（500字）
        if all_tools:
            tools_html = ""
            for t in all_tools:
                tname = t.get('tool_name', '?')
                targs = t.get('arguments', '') or ''
                tresult = t.get('result_preview', '') or ''
                # Parse args if JSON string
                try:
                    args_obj = _j3.loads(targs) if isinstance(targs, str) else targs
                    targs = ' '.join(f'{k}={v}' for k,v in (args_obj.items() if isinstance(args_obj, dict) else []))
                except: pass
                tools_html += f"""<div style="margin:8px 0;padding:10px;background:rgba(255,255,255,.03);border-left:3px solid var(--yellow);border-radius:4px">
                  <div style="font-size:12px;margin-bottom:4px"><b style="color:var(--yellow)">{tname}</b> <span style="color:var(--muted);font-size:10px">{targs}</span></div>
                  <pre style="font-size:11px;max-height:250px;overflow:auto;white-space:pre-wrap;background:rgba(0,0,0,.3);padding:8px;border-radius:4px;margin:0">{tresult}</pre>
                </div>"""
            content += f"""<div class="card" style="border-left:3px solid var(--yellow)"><b>🔧 工具调用 & 结果 ({len(all_tools)}项)</b>{tools_html}</div>"""
    except: pass
    # === 新增：Judge 评分 ===
    judge_dims = ""
    if d.get("judge_dimensions_json"):
        try:
            import json as _j
            dims = _j.loads(d["judge_dimensions_json"])
            for name, dd in dims.items():
                s = int(dd.get("score", 0))
                bar = "▮"*s + "▯"*(5-s)
                judge_dims += f'<div style="margin:2px 0;font-size:11px">{bar} {name}: {dd.get("score","?")}/5 — {dd.get("comment","")[:120]}</div>'
        except: pass
    content += f"""
    <div class="card" style="border-left:3px solid orange">
      <b>LLM Judge:</b> {d.get("judge_score","?")}/50 | is_badcase: {d.get("judge_is_badcase","?")} | {d.get("judge_badcase_type","?")}<br>{judge_dims}
    </div>
    """

    # === 新增：人工点评 ===
    human = d.get("human_is_badcase")
    ht = d.get("human_badcase_type", "")
    hn = d.get("human_notes", "")
    checked1 = "checked" if human == 1 else ""
    checked0 = "checked" if human == 0 else ""
    types = [("","--类型--"),("hallucination","幻觉"),("persona_break","人设分裂"),("wrong_fact","事实错误"),("bad_style","风格问题"),("contradiction","前后矛盾"),("other","其他")]
    sel_opts = "".join(f'<option value="{v}" {"selected" if ht==v else ""}>{l}</option>' for v,l in types)
    content += f"""
    <div class="card" style="border-left:3px solid green">
      <b>人工点评:</b>
      <form id="gt-form" style="margin-top:8px">
        <label style="display:block;margin:8px 0"><input type="radio" name="is_badcase" value="1" {checked1}> badcase <input type="radio" name="is_badcase" value="0" {checked0} style="margin-left:12px"> 正常</label>
        <select name="badcase_type" style="background:#161b22;color:#c9d1d9;border:1px solid #30363d;padding:4px 8px;border-radius:4px;margin:4px 0">{sel_opts}</select>
        <textarea name="notes" rows="2" placeholder="点评..." style="width:100%;background:#161b22;color:#c9d1d9;border:1px solid #30363d;padding:8px;border-radius:4px;font-size:13px;margin:4px 0">{hn or ""}</textarea>
        <button type="submit" style="background:#58a6ff;color:#fff;border:none;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px">保存</button> <span id="save-status" style="font-size:12px;color:#3fb950"></span>
      </form>
    </div>
    <script>document.getElementById("gt-form").addEventListener("submit",async function(e){{e.preventDefault();var f=e.target;var r=await fetch("/api/gt/{id}",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{is_badcase:f.is_badcase.value==="1",badcase_type:f.badcase_type.value,notes:f.notes.value}})}});document.getElementById("save-status").textContent=(await r.json()).success?"OK":"FAIL";}});</script>
    """
    return HTMLResponse(_page(f"Tick {d.get('session_id','')}:#{d['tick_id']}", content, "/ticks"))


    db = get_db()
    conn = db._get_conn()
    # Show ticks where Judge might be wrong: high score but human disagrees, or low score but human says OK
    rows = conn.execute("""SELECT id, session_id, tick_id, chat_name, judge_score, judge_is_badcase, human_is_badcase, human_badcase_type, raw_response
        FROM tick_log WHERE judge_score > 0 AND (human_is_badcase IS NULL OR human_is_badcase != judge_is_badcase)
        ORDER BY created_at DESC, tick_id DESC LIMIT 50""").fetchall()
    conn.close()
    rows_html = ""
    for r in rows:
        j = "✅正常" if r["judge_is_badcase"] == 0 else "❌badcase"
        h = "—" if r["human_is_badcase"] is None else ("✅正常" if r["human_is_badcase"] == 0 else f"❌{r['human_badcase_type']}")
        cls = "" if r["human_is_badcase"] is None else ("style='color:var(--yellow)'" if r["human_is_badcase"] != r["judge_is_badcase"] else "")
        rows_html += f"""<tr {cls}><td><a href="/ticks/{r['id']}" style="color:var(--blue)">{r.get('session_id','')}:#{r['tick_id']}</a></td>
          <td>{r['chat_name']}</td><td>{r['judge_score']:.0f}</td><td>{j}</td><td>{h}</td>
          <td style="font-size:11px;color:var(--muted)">{(r['raw_response'] or '')[:60]}</td></tr>"""

    content = f"""<p style="color:var(--muted);font-size:13px;margin-bottom:12px">标注 Judge 判定可能错误的 tick。点击 tick 进入详情页，底部可设置 GT。</p>
    <table><tr><th>Tick</th><th>聊天</th><th>Judge分</th><th>Judge判</th><th>人工判</th><th>回复</th></tr>{rows_html}</table>"""
    return HTMLResponse(_page("GT 标注", content, "/gt"))


@app.get("/review", response_class=HTMLResponse)
def review_list():
    db = get_db()
    conn = db._get_conn()
    rows = conn.execute("SELECT id, draft_id, chat_name, status, badcase_type, severity, confidence, overall_score, judge_reason FROM cases ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    rows_html = ""
    for r in rows:
        rows_html += f"""<tr><td><a href="/review/{r['draft_id']}" style="color:var(--blue)">{r['draft_id'][:40]}</a></td>
          <td>{r['chat_name']}</td><td>{r['status']}</td><td>{r['badcase_type']}</td>
          <td>{r['confidence']:.0%}</td><td>{r['overall_score']:.0f}</td></tr>"""

    return HTMLResponse(_page("Badcase 审核", f"""<table><tr><th>Draft</th><th>聊天</th><th>状态</th><th>类型</th><th>置信</th><th>分</th></tr>{rows_html}</table>""", "/review"))


@app.post("/api/gt/{id}")
async def save_gt(id: int, request: Request):
    body = await request.json()
    db = get_db()
    conn = db._get_conn()
    conn.execute("""UPDATE tick_log SET
        human_is_badcase=?, human_badcase_type=?, human_notes=?,
        human_labeled_at=datetime('now','localtime')
        WHERE id=?""",
        (1 if body.get("is_badcase") else 0,
         body.get("badcase_type", ""),
         body.get("notes", ""),
         id))
    conn.commit()
    conn.close()
    return JSONResponse({"success": True})


# ── 截图 + OCR 查看 ──

DEBUG_DIR = Path(__file__).parent.parent / "data" / "debug"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "data" / "screenshots"

@app.get("/api/screenshot-image/{filename:path}")
def serve_screenshot(filename: str):
    """返回截图图片文件"""
    # 1. data/screenshots/
    path = SCREENSHOTS_DIR / filename
    if path.exists():
        return FileResponse(str(path), media_type="image/png")
    # 2. /tmp
    tmp_path = Path("/tmp") / filename
    if tmp_path.exists():
        return FileResponse(str(tmp_path), media_type="image/png")
    # 3. 绝对路径
    abs_path = Path(filename)
    if abs_path.is_absolute() and abs_path.exists():
        return FileResponse(str(abs_path), media_type="image/png")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/screenshots", response_class=HTMLResponse)
def screenshots_list(page: int = Query(1, ge=1), limit: int = Query(20, ge=5, le=100)):
    """截图 + OCR 列表页 — 用于评测多模态 API。数据来自 debug JSON，覆盖所有 tick。"""
    # 收集所有 debug JSON，按 tick_id 降序
    all_debug = []
    for f in DEBUG_DIR.glob("tick_*.json"):
        try:
            tid_str = f.stem.split("_")[-1]
            tid = int(tid_str)
            mtime = f.stat().st_mtime
            all_debug.append((tid, mtime, f))
        except (ValueError, IndexError):
            continue
    all_debug.sort(key=lambda x: x[1], reverse=True)
    total = len(all_debug)
    offset = (page - 1) * limit
    page_items = all_debug[offset:offset + limit]

    # 批量查询 tick_log 统一 ID 显示
    tick_map = {}
    if page_items:
        db = get_db()
        conn = db._get_conn()
        try:
            placeholders = ",".join("?" for _ in page_items)
            rows = conn.execute(
                f"SELECT id, tick_id, session_id, chat_name FROM tick_log WHERE tick_id IN ({placeholders})",
                [tid for tid, _, _ in page_items]
            ).fetchall()
            for r in rows:
                tick_map[r["tick_id"]] = {"id": r["id"], "session_id": r["session_id"] or "", "chat_name": r["chat_name"] or ""}
        finally:
            conn.close()

    rows_html = ""
    for tid, mtime, fpath in page_items:
        ts = __import__('datetime').datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        sp = ""
        ocr_summary = ""
        api_info = ""
        chat_name = "-"
        try:
            dbg = _json.loads(fpath.read_text(encoding="utf-8"))
            sp = dbg.get("screenshot_path", "") or dbg.get("perception_screenshot_path", "") or ""
            ocr_count = len(dbg.get("ocr_elements", []))
            layout_msgs = len(dbg.get("extraction_messages", []))
            chat_items = len(dbg.get("layout_chat_list_nicknames", []))
            chat_name = dbg.get("perception_chat_name", "") or dbg.get("bot_chat_name", "") or "-"
            msg_new = dbg.get("bot_new_messages_count", 0)
            ocr_summary = f"OCR:{ocr_count}项 msg:{layout_msgs}条 chat:{chat_items}项"
            if dbg.get("api_prompt"):
                api_info = f'<span style="color:var(--green)">API</span>'
            elif ocr_count > 0 or layout_msgs > 0:
                api_info = f'<span style="color:var(--muted)">本地</span>'
            else:
                api_info = f'<span style="color:var(--yellow)">跳过</span>'
            if msg_new:
                ocr_summary += f" 新:{msg_new}"
        except Exception:
            pass

        # 统一 ID 显示：session_id:#tick_id，链接到 /screenshots/{id}
        info = tick_map.get(tid, {})
        db_id = info.get("id", tid)
        session_id = info.get("session_id", "")
        if info.get("chat_name") and chat_name == "-":
            chat_name = info["chat_name"]

        name_link = f'{session_id}:#{tid}' if session_id else f'#{tid}'
        fname = Path(sp).name if sp else ""
        img_tag = f'<img src="/api/screenshot-image/{fname}" style="max-width:240px;max-height:160px;border-radius:4px;border:1px solid var(--border)" loading="lazy" onerror="this.style.display=\'none\'">' if fname else '<span style="color:var(--muted)">—</span>'

        rows_html += f"""
        <tr>
          <td><a href="/screenshots/{db_id}" style="color:var(--blue)">{name_link}</a></td>
          <td>{ts}</td>
          <td>{chat_name[:12]}</td>
          <td>{img_tag}</td>
          <td style="font-size:12px">{ocr_summary}</td>
          <td>{api_info}</td>
        </tr>"""

    content = f"""
    <p style="color:var(--muted);font-size:13px;margin-bottom:12px">截图、OCR 识别结果、多模态 API — 数据来自 {total} 个 debug JSON（覆盖所有 tick）</p>
    <table>
      <tr><th>Tick</th><th>时间</th><th>聊天</th><th>截图</th><th>OCR/Layout</th><th>API</th></tr>
      {rows_html}
    </table>
    <div style="margin-top:12px;font-size:13px">
      <a href="?page={page-1}&limit={limit}" style="color:var(--blue);margin-right:12px" {'hidden' if page<=1 else ''}>上一页</a>
      第 {page} 页 / 共 {(total+limit-1)//limit} 页
      <a href="?page={page+1}&limit={limit}" style="color:var(--blue);margin-left:12px">下一页</a>
    </div>"""
    return HTMLResponse(_page("截图 & OCR 查看", content, "/screenshots"))


@app.get("/screenshots/{id}", response_class=HTMLResponse)
def screenshot_detail(id: int):
    """单个 tick 的截图 + OCR + Layout + API 详细视图（数据来自 debug JSON）"""
    # 查询 tick_log 获取 tick_id 和 session_id
    db = get_db()
    conn = db._get_conn()
    try:
        row = conn.execute(
            "SELECT tick_id, session_id, chat_name, screenshot_path FROM tick_log WHERE id = ?",
            (id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return HTMLResponse("<h1>Tick not found</h1><p>没有找到 id #%d 的 tick 数据</p>" % id)

    tick_id = row["tick_id"]
    session_id = row["session_id"] or ""
    db_chat_name = row["chat_name"] or ""
    db_screenshot = row["screenshot_path"] or ""

    # 找 debug JSON
    debug_files = sorted(DEBUG_DIR.glob(f"tick_*_{tick_id}.json"))
    if not debug_files:
        return HTMLResponse("<h1>Debug data not found</h1><p>没有找到 tick #%d 的 debug 数据</p>" % tick_id)

    dbg = {}
    sp = db_screenshot
    raw_chat = db_chat_name or str(tick_id)
    ts = ""
    try:
        dbg = _json.loads(debug_files[-1].read_text(encoding="utf-8"))
        if not sp:
            sp = dbg.get("screenshot_path", "") or dbg.get("perception_screenshot_path", "") or ""
        if not db_chat_name:
            raw_chat = dbg.get("perception_chat_name", "") or dbg.get("bot_chat_name", "") or ""
        ts = dbg.get("timestamp", "")[:16]
    except Exception:
        pass

    ocr_html = "<span style='color:var(--muted)'>无 OCR 数据</span>"
    layout_html = "<span style='color:var(--muted)'>无 Layout 数据</span>"
    api_prompt_html = "<span style='color:var(--muted)'>无 API 数据</span>"
    api_response_html = "<span style='color:var(--muted)'>无 API 响应</span>"

    if dbg:
        try:
            # OCR elements
            ocr_elems = dbg.get("ocr_elements", [])
            if ocr_elems:
                ocr_rows = ""
                for e in ocr_elems[:100]:
                    text = e.get("text", "")[:60]
                    bbox = e.get("bbox", [])
                    conf = e.get("confidence", 0)
                    ocr_rows += f"<tr><td style='font-size:10px;color:var(--muted)'>{bbox}</td><td>{text}</td><td>{conf:.0%}</td></tr>"
                ocr_html = f"<table><tr><th>BBox</th><th>Text</th><th>置信度</th></tr>{ocr_rows}</table>"
            else:
                ocr_html = "<span style='color:var(--muted)'>OCR elements 为空（可能为本地跳过路径）</span>"

            # Layout groups
            layout_parts = []
            for key, label in [("layout_left_elements", "左侧聊天列表"), ("layout_right_elements", "右侧消息区"),
                               ("layout_title_elements", "标题栏"), ("layout_input_elements", "输入框"),
                               ("layout_chat_list_groups", "聊天分组"), ("layout_chat_list_nicknames", "昵称列表"),
                               ("layout_chat_list_unread", "未读标记"), ("layout_message_candidates", "消息候选")]:
                val = dbg.get(key, [])
                if val:
                    if isinstance(val, list):
                        items = "<br>".join(str(v)[:100] for v in val[:20])
                        layout_parts.append(f"<div class='card'><b>{label}</b> ({len(val)}):<br><span style='font-size:11px'>{items}</span></div>")
                    else:
                        layout_parts.append(f"<div class='card'><b>{label}</b>: {str(val)[:200]}</div>")
            if layout_parts:
                layout_html = "".join(layout_parts)

            # API prompt & response
            api_prompt = dbg.get("api_prompt", "")
            api_response = dbg.get("api_response", "")
            if api_prompt:
                api_prompt_html = f"<pre style='font-size:10px;max-height:300px;overflow:auto;white-space:pre-wrap;background:rgba(0,0,0,.2);padding:8px;border-radius:4px'>{api_prompt[:5000]}</pre>"
            if api_response:
                api_response_html = f"<pre style='font-size:10px;max-height:300px;overflow:auto;white-space:pre-wrap;background:rgba(0,0,0,.2);padding:8px;border-radius:4px'>{api_response[:5000]}</pre>"

            # 提取消息
            msgs = dbg.get("extraction_messages", [])
            if msgs:
                msgs_html = ""
                for m in msgs[:30]:
                    msgs_html += f"<tr><td>{m.get('sender','')[:20]}</td><td>{m.get('text','')[:80]}</td><td>{m.get('chat_name','')[:20]}</td></tr>"
                layout_parts.append(f"<div class='card'><b>提取的消息</b> ({len(msgs)}):<table><tr><th>发送者</th><th>文本</th><th>聊天</th></tr>{msgs_html}</table></div>")
        except Exception:
            pass

    fname = Path(sp).name if sp else ""
    img_html = f'<img src="/api/screenshot-image/{fname}" style="max-width:100%;border-radius:4px;border:1px solid var(--border)" onerror="this.style.display=\'none\'">' if fname else '<span style="color:var(--muted)">无截图</span>'

    display_id = f'{session_id}:#{tick_id}' if session_id else f'#{tick_id}'
    tick_link = f'<a href="/ticks/{id}" style="color:var(--blue);font-size:13px">→ 查看 Tick 详情</a>'
    content = f"""
    <div class="card"><b>{display_id}</b> — {ts} | {raw_chat} | {tick_link}<br><span style="font-size:11px;color:var(--muted)">{sp}</span></div>

    <div style="display:flex;gap:16px;flex-wrap:wrap">
      <div style="flex:1;min-width:300px">
        <div class="card"><b>📸 截图</b> <span style="font-size:11px;color:var(--muted)">双击看大图</span><br>{img_html}</div>
      </div>
      <div style="flex:2;min-width:400px">
        <div class="card" style="border-left:3px solid var(--blue)"><b>🤖 多模态 API Prompt</b> ({len(dbg.get('api_prompt',''))} 字)<br>{api_prompt_html}</div>
        <div class="card" style="border-left:3px solid var(--green)"><b>🤖 多模态 API Response</b><br>{api_response_html}</div>
      </div>
    </div>

    <details style="margin-top:12px"><summary style="cursor:pointer;color:var(--muted)">📋 OCR 识别结果</summary><div class="card">{ocr_html}</div></details>
    <details style="margin-top:8px"><summary style="cursor:pointer;color:var(--muted)">📐 Layout 分组</summary><div class="card">{layout_html}</div></details>
    <p style="margin-top:12px"><a href="/screenshots" style="color:var(--blue)">返回列表</a></p>
    """
    return HTMLResponse(_page(f"截图 {display_id}", content, "/screenshots"))


# ── Benchmark Dashboard ──

BENCHMARK_JUDGE = Path(__file__).parent.parent / "data" / "reports" / "benchmark_judge.html"
BENCHMARK_REPLY = Path(__file__).parent.parent / "data" / "reports" / "benchmark_reply.html"

def _embed_benchmark(html_path: Path, title: str, active: str) -> str:
    """提取独立 HTML 的 body + style 内容，嵌入 admin 框架。"""
    if not html_path.exists():
        return _page(title, "<p style='color:var(--muted)'>No data. Run scripts/generate_benchmark_dashboard.py</p>", active)
    raw = html_path.read_text(encoding="utf-8")
    # 提取 <style>...</style>
    style_start = raw.find("<style>")
    style_end = raw.find("</style>")
    style = raw[style_start:style_end + 8] if style_start >= 0 and style_end > style_start else ""
    # 提取 <body>...</body>
    body_start = raw.find("<body>")
    body_end = raw.find("</body>")
    if body_start >= 0 and body_end > body_start:
        body = raw[body_start + 6:body_end]
        # 去掉 <h1>
        h1_end = body.find("</h1>")
        if h1_end > 0:
            body = body[h1_end + 5:]
        return _page(title, style + body, active)
    return _page(title, raw, active)

@app.get("/benchmark/judge", response_class=HTMLResponse)
def benchmark_judge():
    return HTMLResponse(_embed_benchmark(BENCHMARK_JUDGE, "Judge Quality Benchmark", "/benchmark/judge"))

@app.get("/benchmark/reply", response_class=HTMLResponse)
def benchmark_reply():
    return HTMLResponse(_embed_benchmark(BENCHMARK_REPLY, "Bot 回复质量 Benchmark", "/benchmark/reply"))

@app.post("/api/refresh-benchmark")
def refresh_benchmark():
    import subprocess
    script = str(Path(__file__).parent.parent / "scripts" / "generate_benchmark_dashboard.py")
    try:
        subprocess.run(["python3", script], timeout=60, capture_output=True)
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


# ── 实验 A/B 对比 ──

@app.get("/experiments", response_class=HTMLResponse)
def experiments_list():
    db = get_db()
    conn = db._get_conn()
    exps = conn.execute("SELECT * FROM experiments ORDER BY id DESC").fetchall()
    conn.close()

    if not exps:
        content = "<p style='color:var(--muted)'>暂无实验。运行 <code>python3 scripts/run_experiment.py --exp &lt;name&gt; --all-labeled</code></p>"
        return HTMLResponse(_page("A/B 实验", content, "/experiments"))

    rows = ""
    for e in exps:
        icon = "✅" if e["is_improvement"] else "—"
        bc_diff = (e["control_badcase_rate"] or 0) - (e["exp_badcase_rate"] or 0)
        score_diff = (e["exp_avg_score"] or 0) - (e["control_avg_score"] or 0)
        rows += f"""<tr>
          <td><a href="/experiments/{e['id']}" style="color:var(--blue)">{e['name']}</a></td>
          <td>{e['description'] or ''}</td>
          <td>{e['n_samples']}</td>
          <td>{(e['control_badcase_rate'] or 0)*100:.0f}% → {(e['exp_badcase_rate'] or 0)*100:.0f}%</td>
          <td>{e['control_avg_score']:.1f} → {e['exp_avg_score']:.1f}</td>
          <td>{icon} {e['summary'] or ''}</td>
          <td style="font-size:11px;color:var(--muted)">{(e['created_at'] or '')[:16]}</td>
        </tr>"""

    content = f"""<table>
    <tr><th>实验</th><th>描述</th><th>N</th><th>Badcase 率</th><th>均分</th><th>结论</th><th>时间</th></tr>
    {rows}</table>"""
    return HTMLResponse(_page("A/B 实验", content, "/experiments"))


@app.get("/experiments/{exp_id}", response_class=HTMLResponse)
def experiment_detail(exp_id: int):
    import json
    db = get_db()
    conn = db._get_conn()

    exp = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
    if not exp:
        conn.close()
        return HTMLResponse("<h1>Experiment not found</h1>")

    dims = json.loads(exp["dimension_diffs_json"] or "{}")

    # Summary
    bc_diff = (exp['control_badcase_rate'] or 0) - (exp['exp_badcase_rate'] or 0)
    score_diff = (exp['exp_avg_score'] or 0) - (exp['control_avg_score'] or 0)
    content = f"""
    <div class="card"><b>🧪 {exp['name']}</b> — {exp['description'] or ''} · N={exp['n_samples']} · 固定 Judge: v4-pro</div>
    <div class="metrics">
      <div class="metric"><div class="val">{(exp['control_badcase_rate'] or 0)*100:.0f}% → {(exp['exp_badcase_rate'] or 0)*100:.0f}%</div><div class="lbl">Badcase 率（{bc_diff:+.0%}）</div></div>
      <div class="metric"><div class="val">{exp['control_avg_score']:.1f} → {exp['exp_avg_score']:.1f}</div><div class="lbl">均分（{score_diff:+.1f}）</div></div>
      <div class="metric"><div class="val">{'✅ 提升' if exp['is_improvement'] else '— 无差异'}</div><div class="lbl">{exp['summary'] or ''}</div></div>
    </div>"""

    # Dimension diffs
    if dims:
        content += '<div class="card"><b>各维度差异（实验 - 基线）：</b><br>'
        for dim, diff in sorted(dims.items(), key=lambda x: -x[1]):
            color = "var(--green)" if diff > 0.1 else ("var(--red)" if diff < -0.1 else "var(--muted)")
            bar_w = min(abs(diff) * 50, 200)
            bar_color = "var(--green)" if diff > 0 else "var(--red)"
            content += f'<div style="display:flex;align-items:center;margin:4px 0"><span style="width:100px;font-size:12px">{dim}</span><span style="color:{color};font-weight:600;width:40px">{diff:+.1f}</span><div style="width:200px;background:rgba(255,255,255,.05);border-radius:3px;height:12px"><div style="width:{bar_w}px;height:12px;background:{bar_color};border-radius:3px"></div></div></div>'
        content += '</div>'

    # Per-tick: side-by-side comparison of actual bot replies
    results = conn.execute("""
        SELECT c.tick_id,
               MAX(CASE WHEN c.config_name='control' THEN c.judge_score END) as c_score,
               MAX(CASE WHEN c.config_name='control' THEN c.judge_is_badcase END) as c_bc,
               MAX(CASE WHEN c.config_name='control' THEN c.bot_reply END) as c_reply,
               MAX(CASE WHEN c.config_name='control' THEN c.judge_dimensions_json END) as c_dims,
               MAX(CASE WHEN c.config_name='control' THEN c.judge_reason END) as c_reason,
               MAX(CASE WHEN c.config_name!='control' THEN c.judge_score END) as e_score,
               MAX(CASE WHEN c.config_name!='control' THEN c.judge_is_badcase END) as e_bc,
               MAX(CASE WHEN c.config_name!='control' THEN c.bot_reply END) as e_reply,
               MAX(CASE WHEN c.config_name!='control' THEN c.judge_dimensions_json END) as e_dims,
               MAX(CASE WHEN c.config_name!='control' THEN c.judge_reason END) as e_reason
        FROM experiment_results c
        WHERE c.experiment_id=?
        GROUP BY c.tick_id ORDER BY c.tick_id
    """, (exp_id,)).fetchall()
    conn.close()

    content += '<h2>📋 逐 Tick 对比</h2>'
    # 获取上下文数据
    conn2 = db._get_conn()
    tick_ids = [r['tick_id'] for r in results]
    ctx_data = {}
    if tick_ids:
        placeholders = ','.join('?' * len(tick_ids))
        ctx_rows = conn2.execute(f"SELECT tick_id, system_prompt, user_prompt, tool_calls_json FROM tick_log WHERE tick_id IN ({placeholders})", tick_ids).fetchall()
        for cr in ctx_rows:
            d = dict(cr)
            ctx_data[d['tick_id']] = d
    conn2.close()

    for r in results:
        c_s = r["c_score"] or 0; e_s = r["e_score"] or 0
        diff = e_s - c_s
        cls = "judge-match" if diff >= 0 else "judge-mismatch"
        c_icon = "❌" if r["c_bc"] else "✅"
        e_icon = "❌" if r["e_bc"] else "✅"
        arrow = "↑" if diff > 1 else ("↓" if diff < -1 else "→")

        ctx = ctx_data.get(r['tick_id'], {})
        sp = ctx.get('system_prompt') or ''
        up = ctx.get('user_prompt') or ''
        tc = (ctx.get('tool_calls_json') or '[]')

        # Parse dimension scores
        c_dims_json = r["c_dims"] or "{}"
        e_dims_json = r["e_dims"] or "{}"
        try: c_dims = json.loads(c_dims_json)
        except: c_dims = {}
        try: e_dims = json.loads(e_dims_json)
        except: e_dims = {}
        dim_comparison = ""
        for dim_name in ["幻觉控制", "时间推理", "回复必要性", "信息准确性", "上下文理解"]:
            cv = c_dims.get(dim_name, {}).get("score", 0)
            ev = e_dims.get(dim_name, {}).get("score", 0)
            d = ev - cv
            color = "var(--green)" if d > 0 else ("var(--red)" if d < 0 else "var(--muted)")
            dim_comparison += f'<span style="margin:2px 6px;font-size:10px">{dim_name}: {cv}→{ev} <b style="color:{color}">{d:+d}</b></span>'

        content += f"""<div class="card {cls}">
  <h3><a href="/ticks/{r['tick_id']}" style="color:var(--blue)">#{r['tick_id']}</a> {arrow} {diff:+.0f}分</h3>
  <table><tr>
    <th style="width:50%">基线 {c_icon} {c_s:.0f}分</th>
    <th style="width:50%">实验组 {e_icon} {e_s:.0f}分</th>
  </tr><tr>
    <td style="font-size:12px;white-space:pre-wrap">{r['c_reply'] or ''}</td>
    <td style="font-size:12px;white-space:pre-wrap">{r['e_reply'] or ''}</td>
  </tr></table>
  <div style="margin:4px 0;color:var(--muted);font-size:10px">{dim_comparison}</div>
  <div style="font-size:11px;color:var(--muted);margin:4px 0">基线理由: {r['c_reason'] or ''}</div>
  <div style="font-size:11px;color:var(--muted);margin:4px 0">实验理由: {r['e_reason'] or ''}</div>
  <details style="margin-top:4px"><summary style="cursor:pointer;font-size:11px;color:var(--blue)">上下文（System: {len(sp)}字 User: {len(up)}字）</summary>
    <div style="font-size:10px;max-height:400px;overflow:auto;white-space:pre-wrap;background:rgba(0,0,0,.2);padding:8px;border-radius:3px;margin-top:4px">{up}</div>
  </details>
</div>"""

    return HTMLResponse(_page(f"实验: {exp['name']}", content, "/experiments"))


if __name__ == "__main__":
    import uvicorn
    print("wechat-twin Admin → http://localhost:8765")
    uvicorn.run(app, host="0.0.0.0", port=8766)
