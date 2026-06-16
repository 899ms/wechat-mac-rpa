#!/usr/bin/env python3
"""L4 Action Layer 单元测试"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.action.message_sender import MessageSender, WeChatMessageSender
from src.action.ui_interactor import PyAutoGUIInteractor, UIInteractor
from src.models.base import ActionResult, ChatListItem, Rect


class TestMessageSenderInterface:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            MessageSender()


class TestWeChatMessageSender:
    def test_send_invokes_pbcopy_and_osascript_with_correct_args(self):
        sender = WeChatMessageSender()
        text = "你好，世界"

        with patch("src.action.message_sender.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = sender.send(text)

        assert result.success is True
        assert result.sent_text == text

        # Should be called 4 times: activate WeChat, pbcopy, focus input, paste AppleScript
        assert mock_run.call_count == 4

        calls = mock_run.call_args_list

        # 1. Activate WeChat
        assert calls[0][0][0] == [
            "osascript",
            "-e",
            'tell application "WeChat" to activate',
        ]

        # 2. pbcopy with encoded text
        assert calls[1][0][0] == ["pbcopy"]
        assert calls[1][1]["input"] == text.encode("utf-8")
        assert calls[1][1]["timeout"] == 2

        # 3. Focus input box AppleScript
        assert calls[2][0][0][0] == "osascript"
        assert calls[2][0][0][1] == "-e"
        assert "tell application" in calls[2][0][0][2]
        assert calls[2][1]["capture_output"] is True
        assert calls[2][1]["timeout"] == 5

        # 4. AppleScript paste
        assert calls[3][0][0][0] == "osascript"
        assert calls[3][0][0][1] == "-e"
        script = calls[3][0][0][2]
        assert 'keystroke "v" using command down' in script
        assert "keystroke return" in script
        assert calls[3][1]["capture_output"] is True
        assert calls[3][1]["timeout"] == 5

    def test_send_includes_wechat_activation_step(self):
        sender = WeChatMessageSender()

        with patch("src.action.message_sender.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            sender.send("test")

        calls = mock_run.call_args_list
        assert calls[0][0][0] == [
            "osascript",
            "-e",
            'tell application "WeChat" to activate',
        ]

    def test_send_returns_success_action_result(self):
        sender = WeChatMessageSender()
        text = "hello"

        with patch("src.action.message_sender.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = sender.send(text)

        assert isinstance(result, ActionResult)
        assert result.success is True
        assert result.sent_text == text
        assert result.error is None

    def test_send_returns_failure_action_result_on_subprocess_error(self):
        sender = WeChatMessageSender()

        with patch("src.action.message_sender.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "pbcopy")
            result = sender.send("hello")

        assert isinstance(result, ActionResult)
        assert result.success is False
        assert result.error is not None
        assert "CalledProcessError" in result.error or "pbcopy" in result.error

    def test_send_image_not_implemented(self):
        sender = WeChatMessageSender()
        result = sender.send_image("/tmp/test.png")
        assert isinstance(result, ActionResult)
        assert result.success is False
        assert "not implemented" in result.error.lower()

    def test_send_file_file_not_exists(self):
        sender = WeChatMessageSender()
        result = sender.send_file("/tmp/nonexistent_file_12345.txt")
        assert isinstance(result, ActionResult)
        assert result.success is False
        assert "不存在" in result.error

    def test_send_file_silent_mode_returns_success(self):
        sender = WeChatMessageSender(silent_mode=True)
        result = sender.send_file("/tmp/nonexistent_file_12345.txt")
        assert isinstance(result, ActionResult)
        assert result.success is True
        assert "[文件]" in result.sent_text

    def test_send_file_invokes_copy_and_paste_scripts(self):
        import tempfile

        sender = WeChatMessageSender()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            tmp_path = f.name

        try:
            with patch("src.action.message_sender.subprocess.run") as mock_run:
                # 让 frontmost 校验返回 WeChat，使流程能继续到文件复制/粘贴
                def _side_effect(*args, **kwargs):
                    mocked = MagicMock(returncode=0)
                    cmd = args[0] if args else []
                    if isinstance(cmd, list) and cmd and cmd[0] == "osascript":
                        script = cmd[-1] if cmd else ""
                        if "frontApp" in script:
                            mocked.stdout = b"WeChat"
                    return mocked

                mock_run.side_effect = _side_effect
                result = sender.send_file(tmp_path)

            assert result.success is True
            assert "[文件]" in result.sent_text

            # 验证整个流程调用了 subprocess.run（至少包括 frontmost/focus/copy/paste/return）
            assert mock_run.call_count >= 4
        finally:
            import os
            os.unlink(tmp_path)


class TestUIInteractorInterface:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            UIInteractor()


class TestPyAutoGUIInteractor:
    def test_click_chat_item_calculates_correct_center_from_rect(self):
        interactor = PyAutoGUIInteractor()
        item = ChatListItem(
            nickname="小王",
            last_message_preview="在吗",
            unread_count="1",
            timestamp="12:34",
            rect=Rect(x=10, y=20, width=100, height=60),
        )

        with patch("src.action.ui_interactor.pyautogui") as mock_pyautogui:
            mock_pyautogui.click.return_value = None
            result = interactor.click_chat_item(item)

        assert result is True
        # center x = 10 + 100/2 = 60, center y = 20 + 60/2 = 50
        mock_pyautogui.click.assert_called_once_with(60, 50)

    def test_click_input_box_returns_bool(self):
        interactor = PyAutoGUIInteractor()

        with patch("src.action.ui_interactor.pyautogui") as mock_pyautogui:
            mock_pyautogui.click.return_value = None
            result = interactor.click_input_box()

        assert isinstance(result, bool)
        assert result is True
        mock_pyautogui.click.assert_called_once()

    def test_click_chat_item_returns_false_on_exception(self):
        interactor = PyAutoGUIInteractor()
        item = ChatListItem(
            nickname="小王",
            last_message_preview="在吗",
            unread_count="1",
            timestamp="12:34",
            rect=Rect(x=10, y=20, width=100, height=60),
        )

        with patch("src.action.ui_interactor.pyautogui") as mock_pyautogui:
            mock_pyautogui.click.side_effect = Exception("click failed")
            result = interactor.click_chat_item(item)

        assert result is False
