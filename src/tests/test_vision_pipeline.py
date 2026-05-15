#!/usr/bin/env python3
"""L3.5 VisionPipeline 单元测试"""

import pytest
from unittest.mock import Mock, patch

from src.perception.vision_pipeline import VisionPipeline
from src.layout.profile import PROFILE_WECHAT_MAC_1760X1280
from src.models.base import (
    Point, Rect, OCRTextElement, ChatMessage, ChatListItem,
    SenderType, PerceptionResult
)
from src.layout.layout_parser import UILayout


class TestVisionPipeline:
    @pytest.fixture
    def pipeline(self):
        return VisionPipeline(PROFILE_WECHAT_MAC_1760X1280)

    def test_perceive_success(self, pipeline):
        """正常感知流程返回 PerceptionResult"""
        # Mock capture
        mock_capture = Mock()
        mock_capture.capture.return_value = Mock(
            image_path="/tmp/test.png",
            window_rect=Rect(0, 0, 1760, 1280),
            scale_factor=1.0
        )
        pipeline.capture = mock_capture

        # Mock OCR
        elem = OCRTextElement(
            text="hi", bbox=Rect(500, 100, 50, 20),
            center=Point(525, 110), confidence=0.9
        )
        mock_ocr = Mock()
        mock_ocr.recognize.return_value = [elem]
        pipeline.ocr = mock_ocr

        # Mock Layout
        layout = UILayout(
            chat_name="测试群",
            chat_list_items=[ChatListItem(
                nickname="小王", last_message_preview="在吗",
                unread_count="", timestamp="",
                rect=Rect(0, 0, 300, 60)
            )],
            title_elements=[elem],
            input_elements=[],
            timestamp_elements=[],
            self_bubbles=[],
            message_candidates=[elem]
        )
        mock_layout = Mock()
        mock_layout.parse.return_value = layout
        mock_layout.profile = PROFILE_WECHAT_MAC_1760X1280
        mock_layout.debug_info = {"chat_list": {"groups": []}}
        pipeline.layout = mock_layout

        # Mock Extractor
        msg = ChatMessage(
            text="hi", sender="小王",
            sender_type=SenderType.OTHER, chat_name="测试群"
        )
        mock_extractor = Mock()
        mock_extractor.extract.return_value = [msg]
        pipeline.extractor = mock_extractor

        result = pipeline.perceive()

        assert isinstance(result, PerceptionResult)
        assert result.chat_name == "测试群"
        assert len(result.messages) == 1
        assert len(result.chat_list_items) == 1
        assert result.screenshot_path == "/tmp/test.png"

        mock_capture.capture.assert_called_once()
        mock_ocr.recognize.assert_called_once_with("/tmp/test.png")
        mock_layout.parse.assert_called_once()
        mock_extractor.extract.assert_called_once()

    def test_perceive_capture_failure_returns_none(self, pipeline):
        """Capture 失败时返回 None"""
        mock_capture = Mock()
        mock_capture.capture.side_effect = Exception("window not found")
        pipeline.capture = mock_capture

        result = pipeline.perceive()
        assert result is None

    def test_perceive_ocr_empty(self, pipeline):
        """OCR 为空时仍然返回有效 PerceptionResult"""
        mock_capture = Mock()
        mock_capture.capture.return_value = Mock(
            image_path="/tmp/empty.png",
            window_rect=Rect(0, 0, 1760, 1280),
            scale_factor=1.0
        )
        pipeline.capture = mock_capture

        mock_ocr = Mock()
        mock_ocr.recognize.return_value = []
        pipeline.ocr = mock_ocr

        layout = UILayout(
            chat_name="", chat_list_items=[],
            title_elements=[], input_elements=[],
            timestamp_elements=[], self_bubbles=[],
            message_candidates=[]
        )
        mock_layout = Mock()
        mock_layout.parse.return_value = layout
        mock_layout.profile = PROFILE_WECHAT_MAC_1760X1280
        mock_layout.debug_info = {"chat_list": {"groups": []}}
        pipeline.layout = mock_layout

        mock_extractor = Mock()
        mock_extractor.extract.return_value = []
        pipeline.extractor = mock_extractor

        result = pipeline.perceive()
        assert isinstance(result, PerceptionResult)
        assert result.messages == []
