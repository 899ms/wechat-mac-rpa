#!/usr/bin/env python3
"""WindowCapture 窗口异常恢复测试"""

import unittest
from unittest.mock import Mock, patch

from src.capture.window_capture import (
    WindowCapture, WindowNotFoundError, WeChatNotReadyError
)


class TestWindowCaptureRecovery(unittest.TestCase):
    """测试 WindowCapture 对异常小窗口的恢复逻辑"""

    def _make_mock_window(self, owner, x, y, width, height, window_id=1):
        return {
            'kCGWindowOwnerName': owner,
            'kCGWindowOwnerPID': 12345,
            'kCGWindowBounds': {
                'X': x, 'Y': y, 'Width': width, 'Height': height
            },
            'kCGWindowNumber': window_id,
        }

    @patch('src.capture.window_capture.subprocess.run')
    @patch('src.capture.window_capture.time.sleep')
    @patch('src.capture.window_capture.Quartz')
    @patch('src.capture.window_capture.AppKit')
    def test_small_window_triggers_activation_and_retry(
        self, mock_appkit, mock_quartz, mock_sleep, mock_subprocess
    ):
        """窗口尺寸过小时应自动激活微信并重试截图"""
        mock_quartz.CGWindowListCopyWindowInfo.side_effect = [
            [self._make_mock_window('微信', 500, 200, 560, 760)],
            [self._make_mock_window('微信', 100, 100, 1760, 1280)],
        ]
        mock_quartz.kCGWindowListOptionOnScreenOnly = 1
        mock_quartz.kCGWindowListExcludeDesktopElements = 2
        mock_quartz.kCGNullWindowID = 0
        mock_quartz.kCGWindowOwnerName = 'kCGWindowOwnerName'
        mock_quartz.kCGWindowBounds = 'kCGWindowBounds'

        mock_appkit.NSScreen.mainScreen.return_value.backingScaleFactor.return_value = 1.0

        capture = WindowCapture()
        result = capture.capture()

        # 应自动调用 activate WeChat
        mock_subprocess.assert_any_call(
            ['osascript', '-e', 'tell application "WeChat" to activate'],
            timeout=3, capture_output=True
        )
        # 应 sleep 等待
        mock_sleep.assert_called()
        # 最终结果应为正常窗口
        self.assertEqual(result.window_rect.width, 1760)
        self.assertEqual(result.window_rect.height, 1280)

    @patch('src.capture.window_capture.subprocess.run')
    @patch('src.capture.window_capture.time.sleep')
    @patch('src.capture.window_capture.Quartz')
    @patch('src.capture.window_capture.AppKit')
    def test_persistent_small_window_raises_not_ready(
        self, mock_appkit, mock_quartz, mock_sleep, mock_subprocess
    ):
        """激活重试后仍然只有小窗口时，应抛出 WeChatNotReadyError"""
        mock_quartz.CGWindowListCopyWindowInfo.return_value = [
            self._make_mock_window('微信', 500, 200, 560, 760),
        ]
        mock_quartz.kCGWindowListOptionOnScreenOnly = 1
        mock_quartz.kCGWindowListExcludeDesktopElements = 2
        mock_quartz.kCGNullWindowID = 0
        mock_quartz.kCGWindowOwnerName = 'kCGWindowOwnerName'
        mock_quartz.kCGWindowBounds = 'kCGWindowBounds'

        mock_appkit.NSScreen.mainScreen.return_value.backingScaleFactor.return_value = 1.0

        capture = WindowCapture()
        with self.assertRaises(WeChatNotReadyError) as ctx:
            capture.capture()

        self.assertIn("扫码", str(ctx.exception))
        mock_subprocess.assert_any_call(
            ['osascript', '-e', 'tell application "WeChat" to activate'],
            timeout=3, capture_output=True
        )

    @patch('src.capture.window_capture.subprocess.run')
    @patch('src.capture.window_capture.Quartz')
    @patch('src.capture.window_capture.AppKit')
    def test_no_window_raises_window_not_found(
        self, mock_appkit, mock_quartz, mock_subprocess
    ):
        """完全找不到微信窗口时保持原有行为"""
        mock_quartz.CGWindowListCopyWindowInfo.return_value = []
        mock_quartz.kCGWindowListOptionOnScreenOnly = 1
        mock_quartz.kCGWindowListExcludeDesktopElements = 2
        mock_quartz.kCGNullWindowID = 0
        mock_quartz.kCGWindowOwnerName = 'kCGWindowOwnerName'
        mock_quartz.kCGWindowBounds = 'kCGWindowBounds'

        mock_appkit.NSScreen.mainScreen.return_value.backingScaleFactor.return_value = 1.0

        capture = WindowCapture()
        with self.assertRaises(WindowNotFoundError):
            capture.capture()

    @patch('src.capture.window_capture.subprocess.run')
    @patch('src.capture.window_capture.time.sleep')
    @patch('src.capture.window_capture.Quartz')
    @patch('src.capture.window_capture.AppKit')
    def test_small_window_with_login_handler_success(
        self, mock_appkit, mock_quartz, mock_sleep, mock_subprocess
    ):
        """提供 login_handler 且恢复成功时，不应抛异常"""
        # 第1次：小窗口；第2次：激活后仍小；login_handler 成功后第3次变大
        mock_quartz.CGWindowListCopyWindowInfo.side_effect = [
            [self._make_mock_window('微信', 500, 200, 560, 760)],
            [self._make_mock_window('微信', 500, 200, 560, 760)],
            [self._make_mock_window('微信', 100, 100, 1760, 1280)],
        ]
        mock_quartz.kCGWindowListOptionOnScreenOnly = 1
        mock_quartz.kCGWindowListExcludeDesktopElements = 2
        mock_quartz.kCGNullWindowID = 0
        mock_quartz.kCGWindowOwnerName = 'kCGWindowOwnerName'
        mock_quartz.kCGWindowBounds = 'kCGWindowBounds'

        mock_appkit.NSScreen.mainScreen.return_value.backingScaleFactor.return_value = 1.0

        from src.action.login_recovery import (
            WeChatLoginHandler, LoginRecoveryResult, LoginRecoveryStatus
        )
        mock_handler = Mock(spec=WeChatLoginHandler)
        mock_handler.handle.return_value = LoginRecoveryResult(
            status=LoginRecoveryStatus.SUCCESS, message="已恢复"
        )

        capture = WindowCapture(login_handler=mock_handler)
        result = capture.capture()

        mock_handler.handle.assert_called_once()
        self.assertEqual(result.window_rect.width, 1760)
        self.assertEqual(result.window_rect.height, 1280)

    @patch('src.capture.window_capture.subprocess.run')
    @patch('src.capture.window_capture.time.sleep')
    @patch('src.capture.window_capture.Quartz')
    @patch('src.capture.window_capture.AppKit')
    def test_small_window_with_login_handler_qrcode(
        self, mock_appkit, mock_quartz, mock_sleep, mock_subprocess
    ):
        """login_handler 返回 NEEDS_QRCODE 时，应抛出 WeChatNotReadyError 并包含提示"""
        mock_quartz.CGWindowListCopyWindowInfo.return_value = [
            self._make_mock_window('微信', 500, 200, 560, 760),
        ]
        mock_quartz.kCGWindowListOptionOnScreenOnly = 1
        mock_quartz.kCGWindowListExcludeDesktopElements = 2
        mock_quartz.kCGNullWindowID = 0
        mock_quartz.kCGWindowOwnerName = 'kCGWindowOwnerName'
        mock_quartz.kCGWindowBounds = 'kCGWindowBounds'

        mock_appkit.NSScreen.mainScreen.return_value.backingScaleFactor.return_value = 1.0

        from src.action.login_recovery import (
            WeChatLoginHandler, LoginRecoveryResult, LoginRecoveryStatus
        )
        mock_handler = Mock(spec=WeChatLoginHandler)
        mock_handler.handle.return_value = LoginRecoveryResult(
            status=LoginRecoveryStatus.NEEDS_QRCODE,
            message="请在微信窗口中扫码登录"
        )

        capture = WindowCapture(login_handler=mock_handler)
        with self.assertRaises(WeChatNotReadyError) as ctx:
            capture.capture()

        self.assertIn("扫码", str(ctx.exception))
