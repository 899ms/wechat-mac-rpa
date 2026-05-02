#!/usr/bin/env python3
"""快速跑 qwen3.5-flash + thinking 前 10 张"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_qwen_vl_ocr import (
    QwenVLOCRClient, LocalOCRBaseline, load_expected_json,
    score_vs_expected, score_vs_local, BenchmarkRun, OCRResult
)

images = sorted(Path('tests/fixtures/legacy/errors').glob('*.png'))[:10]
print(f'Running {len(images)} images with qwen3.5-flash + thinking...\n')

client = QwenVLOCRClient(model='qwen3.5-flash', enable_thinking=True)
local_client = LocalOCRBaseline()

results = []
for img in images:
    expected = load_expected_json(str(img))
    qwen = client.recognize(str(img))
    local = local_client.recognize(str(img))
    vs_exp = score_vs_expected(qwen, expected) if expected else None
    vs_loc = score_vs_local(qwen, local)
    
    score = vs_exp.overall_score if vs_exp else vs_loc.overall_score
    label = "expected" if vs_exp else "local"
    print(f'  {img.name}: qwen={qwen.latency_ms:.0f}ms | {label}={score:.2f}')
    
    results.append(BenchmarkRun(
        image_path=str(img),
        has_expected=expected is not None,
        qwen=qwen, local=local,
        vs_expected=vs_exp, vs_local=vs_loc
    ))

# 保存简化 JSON
out = []
for r in results:
    out.append({
        'image': r.image_path,
        'qwen': {
            'chat_name': r.qwen.chat_name,
            'chat_list': r.qwen.chat_list,
            'messages': r.qwen.messages,
            'latency_ms': r.qwen.latency_ms,
            'error': r.qwen.error,
        },
        'local': {
            'chat_name': r.local.chat_name,
            'chat_list': r.local.chat_list,
            'messages': r.local.messages,
            'latency_ms': r.local.latency_ms,
            'error': r.local.error,
        },
        'vs_expected': {
            'overall_score': r.vs_expected.overall_score,
        } if r.vs_expected else None,
    })

path = Path('results/qwen_vl_ocr/qwen3.5-flash-thinking-top10.json')
path.parent.mkdir(parents=True, exist_ok=True)
with open(path, 'w') as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

avg_lat = sum(r.qwen.latency_ms for r in results) / len(results)
scores = [r.vs_expected.overall_score for r in results if r.vs_expected]
avg_score = sum(scores) / len(scores) if scores else 0
print(f'\nAvg latency: {avg_lat:.0f}ms')
print(f'Avg vs_expected: {avg_score:.3f}')
print(f'Saved to: {path}')
