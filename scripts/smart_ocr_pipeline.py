#!/usr/bin/env python3
"""
智能 OCR Pipeline：本地预过滤 + 云模型精识别

策略：
1. 窗口哈希去重（0ms）
2. 像素差异检测（<50ms）
3. 本地 OCR 预扫描（~1s）
4. 只有检测到"可能有新消息"时才调用云模型

预期效果：
- 无消息时：本地过滤，0 API 调用
- 有消息时：本地确认 + 云模型精识别
- 成本降低 80-95%
"""

import hashlib, sys
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent


class SmartOCRPipeline:
    """智能 OCR 管道：多层过滤减少 API 调用"""

    def __init__(
        self,
        pixel_diff_threshold: float = 0.01,  # 像素差异阈值（1%）
        message_region_ratio: Tuple[float, float, float, float] = (0.35, 0.08, 0.95, 0.88),
        # (x_min, y_min, x_max, y_max) 消息区域相对坐标
    ):
        self.pixel_diff_threshold = pixel_diff_threshold
        self.message_region = message_region_ratio
        self.last_hash: Optional[str] = None
        self.last_pixels: Optional[np.ndarray] = None
        self.last_result: Optional[dict] = None

    # ------------------------------------------------------------------
    # 第 1 层：窗口哈希去重（0ms）
    # ------------------------------------------------------------------
    def _compute_hash(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _check_duplicate(self, image_path: str) -> bool:
        """检查截图是否与上次完全相同"""
        h = self._compute_hash(image_path)
        if self.last_hash == h:
            return True
        self.last_hash = h
        return False

    # ------------------------------------------------------------------
    # 第 2 层：像素差异检测（<50ms）
    # ------------------------------------------------------------------
    def _check_pixel_diff(self, image_path: str) -> Tuple[bool, float]:
        """
        检测截图像素差异。
        返回: (是否有显著变化, 差异比例)
        """
        img = Image.open(image_path).convert("RGB")
        img_array = np.array(img, dtype=np.int16)

        if self.last_pixels is None:
            self.last_pixels = img_array
            return True, 1.0

        # 只对比消息区域（右侧聊天区域）
        h, w = img_array.shape[:2]
        x1, y1, x2, y2 = self.message_region
        region_slice = (
            slice(int(y1 * h), int(y2 * h)),
            slice(int(x1 * w), int(x2 * w)),
        )

        current_region = img_array[region_slice]
        last_region = self.last_pixels[region_slice]

        # 计算像素差异
        diff = np.abs(current_region.astype(np.int16) - last_region.astype(np.int16))
        diff_mask = np.any(diff > 15, axis=2)  # RGB 任一通道差异 > 15
        diff_ratio = np.mean(diff_mask)

        has_change = diff_ratio > self.pixel_diff_threshold
        self.last_pixels = img_array.copy()

        return has_change, diff_ratio

    # ------------------------------------------------------------------
    # 第 3 层：本地 OCR 预扫描（~1s）
    # ------------------------------------------------------------------
    def _local_prescreen(self, image_path: str) -> dict:
        """
        用本地 OCR 快速预扫描，判断是否有新消息特征。
        不追求精度，只追求速度。
        """
        # 复用现有的 VisionOCREngine，但只扫描消息区域
        sys.path.insert(0, str(PROJECT_ROOT))
        from wechat_rpa.ocr.vision_ocr import VisionOCREngine

        ocr = VisionOCREngine()
        elements = ocr.recognize(image_path)

        # 快速统计：是否有绿色气泡区域的文字？
        # 简化判断：消息区域内有"新"的文字元素即认为可能有消息
        has_new_text = len(elements) > 5  # 粗略判断

        return {
            "has_new_text": has_new_text,
            "element_count": len(elements),
            "needs_cloud_ocr": has_new_text,
        }

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def process(self, image_path: str) -> dict:
        """
        处理截图，返回识别结果。
        只在必要时调用云模型。
        """
        result = {
            "image": image_path,
            "skipped": False,
            "skip_reason": None,
            "pixel_diff_ratio": 0.0,
            "local_prescreen": None,
            "cloud_ocr": None,
            "latency_ms": 0,
        }

        start = time.time()

        # 第 1 层：哈希去重
        if self._check_duplicate(image_path):
            result["skipped"] = True
            result["skip_reason"] = "duplicate_hash"
            result["latency_ms"] = (time.time() - start) * 1000
            return result

        # 第 2 层：像素差异
        has_change, diff_ratio = self._check_pixel_diff(image_path)
        result["pixel_diff_ratio"] = diff_ratio
        if not has_change:
            result["skipped"] = True
            result["skip_reason"] = "no_pixel_change"
            result["latency_ms"] = (time.time() - start) * 1000
            return result

        # 第 3 层：本地预扫描
        prescreen = self._local_prescreen(image_path)
        result["local_prescreen"] = prescreen
        if not prescreen["needs_cloud_ocr"]:
            result["skipped"] = True
            result["skip_reason"] = "local_prescreen_negative"
            result["latency_ms"] = (time.time() - start) * 1000
            return result

        # 第 4 层：云模型精识别（这里接入 qwen3-vl-flash/plus）
        # TODO: 接入实际的云模型 OCR
        result["cloud_ocr"] = {"status": "needs_implementation"}
        result["latency_ms"] = (time.time() - start) * 1000

        return result


def demo():
    """演示：用同一张截图连续调用 3 次，观察过滤效果"""
    pipeline = SmartOCRPipeline()

    # 用一张回归截图演示
    image = PROJECT_ROOT / "tests" / "fixtures" / "regression_chat_list_pollution_20260421.png"

    print("=" * 60)
    print("Smart OCR Pipeline 演示")
    print("=" * 60)

    for i in range(3):
        print(f"\n第 {i + 1} 次处理（同一张截图）:")
        result = pipeline.process(str(image))

        if result["skipped"]:
            print(f"  ⏭️  跳过！原因: {result['skip_reason']}")
            print(f"  ⏱️  耗时: {result['latency_ms']:.1f}ms")
        else:
            print(f"  ✅ 需要云模型 OCR")
            print(f"  📊 像素差异: {result['pixel_diff_ratio']:.4f}")
            print(f"  ⏱️  耗时: {result['latency_ms']:.1f}ms")


if __name__ == "__main__":
    demo()
