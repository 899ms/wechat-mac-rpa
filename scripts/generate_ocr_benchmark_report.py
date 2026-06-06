#!/usr/bin/env python3
"""
生成 OCR Benchmark 可视化报告 HTML
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.tests.test_ocr_quality_benchmark import run_benchmark, compute_metrics


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html(output_path: str = "ocr_benchmark_report.html") -> None:
    results = run_benchmark(use_api=False)
    metrics = compute_metrics(results)

    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    total = metrics["total"]
    passed = metrics["passed"]
    pass_rate = metrics["pass_rate"]

    # 颜色判定
    def rate_color(v):
        return "green" if v >= 0.7 else "yellow" if v >= 0.4 else "red"

    # 汇总卡片数据
    cards = [
        ("通过率", f"{pass_rate:.1%}", rate_color(pass_rate), f"{passed}/{total}"),
        ("Chat Name", f"{metrics.get('chat_name_accuracy', 0):.1%}", rate_color(metrics.get('chat_name_accuracy', 0)), ""),
        ("Message Count", f"{metrics.get('message_count_accuracy', 0):.1%}", rate_color(metrics.get('message_count_accuracy', 0)), ""),
        ("Sender 平均", f"{metrics.get('sender_accuracy', 0):.1%}", rate_color(metrics.get('sender_accuracy', 0)), ""),
        ("Sender 100%", f"{metrics.get('sender_perfect_rate', 0):.1%}", rate_color(metrics.get('sender_perfect_rate', 0)), ""),
        ("Text 平均", f"{metrics.get('text_accuracy', 0):.1%}", rate_color(metrics.get('text_accuracy', 0)), ""),
    ]

    parts = []
    parts.append('<!DOCTYPE html>')
    parts.append('<html lang="zh-CN"><head><meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append('<title>OCR Benchmark 报告</title>')
    parts.append('<style>')
    parts.append(':root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--green:#3fb950;--red:#f85149;--yellow:#d29922}')
    parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    parts.append('body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:var(--bg);color:var(--text);padding:24px;max-width:1400px;margin:0 auto}')
    parts.append('h1{text-align:center;margin-bottom:8px}')
    parts.append('.subtitle{text-align:center;color:var(--muted);margin-bottom:24px;font-size:14px}')
    parts.append('.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:28px}')
    parts.append('.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;text-align:center}')
    parts.append('.card h3{font-size:12px;color:var(--muted);margin-bottom:8px;text-transform:uppercase}')
    parts.append('.card .value{font-size:32px;font-weight:700}')
    parts.append('.card .value.green{color:var(--green)}.card .value.red{color:var(--red)}.card .value.yellow{color:var(--yellow)}')
    parts.append('.card .detail{font-size:12px;color:var(--muted);margin-top:4px}')
    parts.append('.category{margin-bottom:24px}')
    parts.append('.category h2{font-size:18px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}')
    parts.append('.case-row{background:var(--card);border:1px solid var(--border);border-radius:8px;margin-bottom:10px;overflow:hidden}')
    parts.append('.case-header{display:flex;align-items:center;gap:12px;padding:12px 16px;cursor:pointer}')
    parts.append('.case-header:hover{background:rgba(255,255,255,.03)}')
    parts.append('.case-header .badge{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600}')
    parts.append('.badge-pass{background:rgba(63,185,80,.15);color:var(--green)}.badge-fail{background:rgba(248,81,73,.15);color:var(--red)}')
    parts.append('.case-header .name{font-weight:600;flex:1;font-size:14px}')
    parts.append('.case-header .mini-stats{display:flex;gap:16px;font-size:13px;color:var(--muted)}')
    parts.append('.case-body{display:none;padding:16px;border-top:1px solid var(--border)}')
    parts.append('.case-body.open{display:block}')
    parts.append('.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}')
    parts.append('@media(max-width:900px){.two-col{grid-template-columns:1fr}}')
    parts.append('.img-box{background:#000;border-radius:6px;overflow:hidden;text-align:center}')
    parts.append('.img-box img{max-width:100%;max-height:420px;display:block;margin:0 auto}')
    parts.append('.msg-table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}')
    parts.append('.msg-table th{text-align:left;padding:6px 8px;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border);font-size:12px}')
    parts.append('.msg-table td{padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}')
    parts.append('.msg-table tr.ok td{color:var(--green)}')
    parts.append('.msg-table tr.err td{color:var(--red)}')
    parts.append('.msg-table .tag{font-size:10px;padding:1px 5px;border-radius:3px;margin-left:4px}')
    parts.append('.tag-ok{background:rgba(63,185,80,.15);color:var(--green)}.tag-err{background:rgba(248,81,73,.15);color:var(--red)}')
    parts.append('pre{margin:0;white-space:pre-wrap;word-break:break-all;font-family:monospace;font-size:12px;color:var(--muted);background:rgba(0,0,0,.2);padding:8px;border-radius:4px}')
    parts.append('.info-row{display:flex;gap:24px;font-size:13px;margin-bottom:8px;flex-wrap:wrap}')
    parts.append('.info-row .label{color:var(--muted)}.info-row .val{font-weight:600}')
    parts.append('.missing-msg{color:var(--red);font-size:12px;margin-top:4px}')
    parts.append('.screenshot-not-found{padding:40px;color:var(--muted);text-align:center}')
    parts.append('</style></head><body>')
    parts.append(f'<h1>📊 OCR Benchmark 报告</h1>')
    parts.append(f'<div class="subtitle">qwen3.6-flash + thinking mode · 共 {total} 个 case</div>')

    # 汇总卡片
    parts.append('<div class="summary">')
    for title, val, color, detail in cards:
        parts.append(f'<div class="card"><h3>{title}</h3><div class="value {color}">{val}</div>')
        if detail:
            parts.append(f'<div class="detail">{detail}</div>')
        parts.append('</div>')
    parts.append('</div>')

    # 按类别
    for cat in sorted(categories.keys()):
        cases = categories[cat]
        cat_passed = sum(1 for c in cases if c.passed)
        parts.append(f'<div class="category"><h2>{cat} <span style="color:var(--muted);font-size:14px;font-weight:400">({cat_passed}/{len(cases)} passed)</span></h2>')

        for r in cases:
            badge = '<span class="badge badge-pass">PASS</span>' if r.passed else '<span class="badge badge-fail">FAIL</span>'
            name_color = 'color:var(--green)' if r.passed else 'color:var(--red)'

            # 找截图
            fixture_dir = PROJECT_ROOT / "tests_integration" / "fixtures"
            screenshot = fixture_dir / f"{r.case_name}.png"
            if not screenshot.exists():
                screenshot = fixture_dir / "legacy" / "errors" / f"{r.case_name}.png"

            if screenshot.exists():
                rel = str(screenshot.relative_to(PROJECT_ROOT))
                img_html = f'<img src="{rel}" alt="{_esc(r.case_name)}">'
            else:
                img_html = '<div class="screenshot-not-found">截图未找到</div>'

            # 消息对比行
            msg_rows = []
            for d in r.message_details:
                ok_cls = "ok" if (d["sender_ok"] and d["text_ok"]) else "err"
                s_tag = '<span class="tag tag-ok">s✓</span>' if d["sender_ok"] else '<span class="tag tag-err">s✗</span>'
                t_tag = '<span class="tag tag-ok">t✓</span>' if d["text_ok"] else '<span class="tag tag-err">t✗</span>'
                msg_rows.append(
                    f'<tr class="{ok_cls}">'
                    f'<td>{d["index"]}</td>'
                    f'<td>{_esc(d["expected_sender"])}{s_tag}</td>'
                    f'<td><pre>{_esc(d["expected_text"][:200])}</pre></td>'
                    f'<td>{_esc(d["actual_sender"])}{s_tag}</td>'
                    f'<td><pre>{_esc(d["actual_text"][:200])}</pre></td>'
                    f'<td>{t_tag}</td>'
                    f'</tr>'
                )

            missing = r.expected_message_count - r.actual_message_count
            extra = r.actual_message_count - r.expected_message_count
            count_note = ""
            if missing > 0:
                count_note = f'<div class="missing-msg">⚠️ 缺失 {missing} 条消息（API 未识别出来）</div>'
            elif extra > 0:
                count_note = f'<div class="missing-msg">⚠️ 多出 {extra} 条消息（API 多识别了）</div>'

            parts.append(f'''
<div class="case-row">
    <div class="case-header" onclick="this.nextElementSibling.classList.toggle('open')">
        {badge}
        <span class="name" style="{name_color}">{_esc(r.case_name)}</span>
        <div class="mini-stats">
            <span>name:{'✅' if r.chat_name_match else '❌'}</span>
            <span>count:{'✅' if r.message_count_match else '❌'}</span>
            <span>sender:{r.sender_accuracy:.0%}</span>
            <span>text:{r.text_accuracy:.0%}</span>
        </div>
    </div>
    <div class="case-body">
        <div class="info-row">
            <div><span class="label">chat_name:</span> <span class="val">{'✅' if r.chat_name_match else '❌'}</span> 预期=<code>{_esc(r.expected_chat_name)}</code> 实际=<code>{_esc(r.actual_chat_name)}</code></div>
            <div><span class="label">message_count:</span> <span class="val">{'✅' if r.message_count_match else '❌'}</span> 预期={r.expected_message_count} 实际={r.actual_message_count}</div>
        </div>
        {count_note}
        <div class="two-col">
            <div>
                <div style="font-size:12px;color:var(--muted);margin-bottom:6px">截图</div>
                <div class="img-box">{img_html}</div>
            </div>
            <div>
                <div style="font-size:12px;color:var(--muted);margin-bottom:6px">消息对比（s=sender, t=text）</div>
                <table class="msg-table">
                    <tr><th>#</th><th>预期Sender</th><th>预期Text</th><th>实际Sender</th><th>实际Text</th><th>Text</th></tr>
                    {''.join(msg_rows)}
                </table>
            </div>
        </div>
    </div>
</div>''')
        parts.append('</div>')

    parts.append('</body></html>')

    out = PROJECT_ROOT / output_path
    out.write_text('\n'.join(parts), encoding='utf-8')
    print(f"报告已生成: {out}")
    print(f"用浏览器打开: file://{out.absolute()}")


if __name__ == "__main__":
    generate_html()
