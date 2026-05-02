#!/usr/bin/env python3
"""
本地预判算法评测

评测策略：
1. 加载连续的截图序列
2. 对每张截图（除第一张），和上一张对比
3. 计算哈希去重 + 像素差异
4. 人工标注是否需要 API
5. 输出召回率、精确率、API 占比
"""

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class EvalResult:
    image: str
    prev_image: str
    hash_same: bool
    pixel_diff_ratio: float
    human_label: bool  # 人工标注：是否需要 API
    algorithm_pass: bool  # 算法判断：是否通过过滤（需要 API）


class LocalPrescreenEvaluator:
    """本地预判算法"""

    def __init__(
        self,
        pixel_diff_threshold: float = 0.005,  # 0.5% 差异阈值
        message_region: tuple = (0.35, 0.08, 0.95, 0.88),
    ):
        self.pixel_diff_threshold = pixel_diff_threshold
        self.message_region = message_region

    def compute_hash(self, path: str) -> str:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def check_pixel_diff(self, current_path: str, prev_path: str) -> float:
        """返回消息区域像素差异比例"""
        curr = np.array(Image.open(current_path).convert("RGB"), dtype=np.int16)
        prev = np.array(Image.open(prev_path).convert("RGB"), dtype=np.int16)

        h, w = curr.shape[:2]
        x1, y1, x2, y2 = self.message_region
        region = (
            slice(int(y1 * h), int(y2 * h)),
            slice(int(x1 * w), int(x2 * w)),
        )

        diff = np.abs(curr[region] - prev[region])
        diff_mask = np.any(diff > 15, axis=2)
        return float(np.mean(diff_mask))

    def evaluate_sequence(self, image_paths: list, human_labels: list) -> list:
        """
        评估一个截图序列。
        image_paths: 按时间排序的截图路径
        human_labels: 每张截图的人工标注（True=需要API）
        """
        results = []
        prev_hash = None
        prev_pixels = None

        for i, path in enumerate(image_paths):
            if i == 0:
                # 第一张没有上一张对比，默认需要 API（或根据标注）
                prev_hash = self.compute_hash(path)
                prev_pixels = np.array(Image.open(path).convert("RGB"), dtype=np.int16)
                results.append(EvalResult(
                    image=Path(path).name,
                    prev_image="N/A",
                    hash_same=False,
                    pixel_diff_ratio=1.0,
                    human_label=human_labels[i],
                    algorithm_pass=True,  # 第一张默认通过
                ))
                continue

            curr_hash = self.compute_hash(path)
            hash_same = (curr_hash == prev_hash)

            if hash_same:
                diff_ratio = 0.0
            else:
                diff_ratio = self.check_pixel_diff(path, image_paths[i - 1])

            algorithm_pass = not hash_same and diff_ratio > self.pixel_diff_threshold

            results.append(EvalResult(
                image=Path(path).name,
                prev_image=Path(image_paths[i - 1]).name,
                hash_same=hash_same,
                pixel_diff_ratio=diff_ratio,
                human_label=human_labels[i],
                algorithm_pass=algorithm_pass,
            ))

            prev_hash = curr_hash
            if not hash_same:
                prev_pixels = np.array(Image.open(path).convert("RGB"), dtype=np.int16)

        return results

    def report(self, results: list) -> dict:
        """生成评测报告"""
        total = len(results)
        # 第一张不参与计算（没有上一张对比）
        eval_results = results[1:]

        tp = sum(1 for r in eval_results if r.human_label and r.algorithm_pass)  # 真正需要API且被正确检出
        fn = sum(1 for r in eval_results if r.human_label and not r.algorithm_pass)  # 需要API但被漏掉
        fp = sum(1 for r in eval_results if not r.human_label and r.algorithm_pass)  # 不需要API但被误报
        tn = sum(1 for r in eval_results if not r.human_label and not r.algorithm_pass)  # 不需要API且被正确过滤

        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        api_ratio = sum(1 for r in eval_results if r.algorithm_pass) / len(eval_results) if eval_results else 0

        return {
            "total_frames": total,
            "evaluated_frames": len(eval_results),
            "true_positives": tp,
            "false_negatives": fn,
            "false_positives": fp,
            "true_negatives": tn,
            "recall": round(recall, 3),
            "precision": round(precision, 3),
            "api_call_ratio": round(api_ratio, 3),
            "api_calls_avoided": tn,
        }


def main():
    import re

    screenshots_dir = PROJECT_ROOT / "tests/fixtures/historical_screenshots"
    annotations_path = PROJECT_ROOT / "tests/fixtures/prescreen_annotations.json"

    # 加载标注
    with open(annotations_path, 'r', encoding='utf-8') as f:
        annotations = json.load(f)

    # 按时间排序截图
    images = sorted(screenshots_dir.glob("wechat_20260417_00*.png"))

    def extract_key(filename):
        m = re.match(r'(wechat_20260417_\d{6})', Path(filename).name)
        return m.group(1) if m else filename

    image_paths = []
    human_labels = []
    for img in images:
        key = extract_key(img.name)
        if key in annotations:
            image_paths.append(str(img))
            human_labels.append(annotations[key]["need_api"])

    print(f"加载截图序列: {len(image_paths)} 张")
    print(f"人工标注 True: {sum(human_labels)} ({sum(human_labels)/len(human_labels)*100:.1f}%)")
    print()

    # 测试不同阈值
    thresholds = [0.001, 0.005, 0.01, 0.02, 0.05, 0.10]

    print("=" * 80)
    print(f"{'Threshold':>10} | {'Recall':>8} | {'Precision':>10} | {'API_Ratio':>10} | {'TP':>4} | {'FN':>4} | {'FP':>4} | {'TN':>4}")
    print("=" * 80)

    for threshold in thresholds:
        evaluator = LocalPrescreenEvaluator(pixel_diff_threshold=threshold)
        results = evaluator.evaluate_sequence(image_paths, human_labels)
        report = evaluator.report(results)

        print(
            f"{threshold:>10.3f} | "
            f"{report['recall']:>8.3f} | "
            f"{report['precision']:>10.3f} | "
            f"{report['api_call_ratio']:>10.3f} | "
            f"{report['true_positives']:>4} | "
            f"{report['false_negatives']:>4} | "
            f"{report['false_positives']:>4} | "
            f"{report['true_negatives']:>4}"
        )

    print("=" * 80)
    print("\n说明:")
    print("  - Threshold: 像素差异阈值 (消息区域变化比例)")
    print("  - Recall: 召回率 = TP/(TP+FN)，越高越好 (不漏掉需要API的截图)")
    print("  - Precision: 精确率 = TP/(TP+FP)，越高越好 (不误报)")
    print("  - API_Ratio: 实际调用API的占比，越低越省钱")
    print("  - TP: 正确检出需要API的截图")
    print("  - FN: 漏掉需要API的截图 (严重错误，会导致漏回复)")
    print("  - FP: 误报不需要API的截图 (浪费API调用)")
    print("  - TN: 正确跳过不需要API的截图 (省钱)")

    # 详细分析最佳阈值
    print("\n" + "=" * 80)
    print("详细分析 (threshold=0.01):")
    print("=" * 80)
    evaluator = LocalPrescreenEvaluator(pixel_diff_threshold=0.01)
    results = evaluator.evaluate_sequence(image_paths, human_labels)
    report = evaluator.report(results)

    for r in results:
        if r.human_label != r.algorithm_pass:
            status = "❌ MISS" if r.human_label else "❌ FALSE_POS"
            print(f"  {status}: {Path(r.image).name}")
            print(f"    hash_same={r.hash_same}, pixel_diff={r.pixel_diff_ratio:.4f}, human={r.human_label}, algo={r.algorithm_pass}")


if __name__ == "__main__":
    main()
