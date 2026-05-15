"""截图模块 - 负责屏幕截图"""
from .window_capture import WindowCapture, CaptureResult, WindowNotFoundError, WeChatNotReadyError

__all__ = ['WindowCapture', 'CaptureResult', 'WindowNotFoundError', 'WeChatNotReadyError']
