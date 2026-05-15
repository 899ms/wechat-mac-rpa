#!/usr/bin/env python3
"""L4 Action Layer - Message Sender

负责发送消息到微信窗口。
"""

import logging
import subprocess
import time
from abc import ABC, abstractmethod

from src.models.base import ActionResult

_logger = logging.getLogger("src.message_sender")


class MessageSender(ABC):
    """消息发送器抽象基类"""

    @abstractmethod
    def send(self, text: str) -> ActionResult:
        """发送文本消息"""
        pass

    @abstractmethod
    def send_image(self, image_path: str) -> ActionResult:
        """发送图片消息"""
        pass

    @abstractmethod
    def send_file(self, file_path: str) -> ActionResult:
        """发送文件"""
        pass


class WeChatMessageSender(MessageSender):
    """基于 AppleScript 的微信消息发送器"""

    def send(self, text: str) -> ActionResult:
        """
        发送文本消息到当前微信聊天。

        流程：
        1. 保存用户当前剪贴板内容（pbpaste）
        2. 激活 WeChat 窗口
        3. 将文本复制到剪贴板 (pbcopy)
        4. 通过 AppleScript 执行 Command+V 粘贴并回车发送
        5. 恢复用户原来的剪贴板内容
        """
        # 保存用户原始剪贴板内容（尽力恢复文本内容）
        original_clipboard = ""
        try:
            r_clip = subprocess.run(
                ["pbpaste"],
                timeout=2,
                capture_output=True,
            )
            if r_clip.returncode == 0:
                original_clipboard = r_clip.stdout.decode("utf-8", errors="replace")
            _logger.info(f"[Sender] 原始剪贴板长度: {len(original_clipboard)} 字符, returncode: {r_clip.returncode}")
        except Exception as e:
            _logger.warning(f"[Sender] 读取原始剪贴板异常: {e}")

        try:
            _logger.info(f"[Sender] 开始发送, 文本长度: {len(text)} 字符")

            # 1. 确保微信窗口在前台，防止消息发到其他应用（带重试）
            activated = False
            last_err = "unknown"
            for attempt in range(3):
                try:
                    r1 = subprocess.run(
                        ["osascript", "-e", 'tell application "WeChat" to activate'],
                        timeout=5,
                        capture_output=True,
                    )
                    _logger.info(f"[Sender] 激活微信 returncode: {r1.returncode}, attempt: {attempt+1}/3")
                    if r1.returncode == 0:
                        activated = True
                        break
                    last_err = r1.stderr.decode("utf-8", errors="replace") if r1.stderr else "unknown"
                except subprocess.TimeoutExpired:
                    last_err = "timeout"
                    _logger.warning(f"[Sender] 激活微信超时 (attempt {attempt+1}/3)")
                if attempt < 2:
                    time.sleep(0.5)
            if not activated:
                return ActionResult(success=False, error=f"激活微信失败: {last_err}")
            time.sleep(0.1)

            # 2. 复制消息到剪贴板
            r2 = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                timeout=2,
                capture_output=True,
            )
            _logger.info(f"[Sender] pbcopy returncode: {r2.returncode}, stderr: {r2.stderr.decode('utf-8', errors='replace').strip()[:200] if r2.stderr else ''}")
            if r2.returncode != 0:
                err = r2.stderr.decode("utf-8", errors="replace") if r2.stderr else "unknown"
                return ActionResult(success=False, error=f"复制剪贴板失败: {err}")
            time.sleep(0.15)

            # 3. 确保焦点在输入框：先点一下窗口中心偏下区域（输入框大致位置）
            focus_script = """
                tell application "System Events"
                    tell process "WeChat"
                        set frontmost to true
                        delay 0.2
                        -- 获取窗口大小，点击底部中央（输入框区域）
                        tell window 1
                            set winPos to position
                            set winSize to size
                            set clickX to (item 1 of winPos) + (item 1 of winSize) / 2
                            set clickY to (item 2 of winPos) + (item 2 of winSize) - 60
                        end tell
                        click at {clickX, clickY}
                        delay 0.2
                    end tell
                end tell
            """
            r_focus = subprocess.run(["osascript", "-e", focus_script], timeout=5, capture_output=True)
            _logger.info(f"[Sender] focus脚本 returncode: {r_focus.returncode}, stderr: {r_focus.stderr.decode('utf-8', errors='replace').strip()[:200] if r_focus.stderr else ''}")

            # 4. 粘贴、验证、发送（带重试）
            max_retries = 3
            for attempt in range(max_retries):
                # 4a. paste
                paste_script = '''
                    tell application "System Events"
                        tell process "WeChat"
                            keystroke "v" using command down
                            delay 0.3
                        end tell
                    end tell
                '''
                r_paste = subprocess.run(
                    ["osascript", "-e", paste_script],
                    timeout=5,
                    capture_output=True,
                )
                _logger.info(f"[Sender] paste attempt {attempt+1}/{max_retries} returncode: {r_paste.returncode}")
                if r_paste.returncode != 0:
                    err = r_paste.stderr.decode("utf-8", errors="replace") if r_paste.stderr else "unknown"
                    _logger.error(f"[Sender] paste AppleScript 失败: {err}")
                    if attempt < max_retries - 1:
                        time.sleep(0.2)
                        continue
                    return ActionResult(success=False, error=f"粘贴失败: {err}")

                # 4a.5 清空剪贴板：确保后续 verify 读的是输入框内容，不是旧剪贴板残留
                subprocess.run(
                    ["pbcopy"],
                    input=b"",
                    timeout=2,
                    capture_output=True,
                )
                time.sleep(0.1)

                # 4b. 验证：Command+A 全选 + Command+C 复制，然后 pbpaste 读取输入框内容
                verify_script = '''
                    tell application "System Events"
                        tell process "WeChat"
                            keystroke "a" using command down
                            delay 0.2
                            keystroke "c" using command down
                            delay 0.2
                        end tell
                    end tell
                '''
                r_verify_script = subprocess.run(
                    ["osascript", "-e", verify_script],
                    timeout=5,
                    capture_output=True,
                )
                _logger.info(f"[Sender] verify select+copy returncode: {r_verify_script.returncode}")

                try:
                    r_verify = subprocess.run(
                        ["pbpaste"],
                        timeout=2,
                        capture_output=True,
                    )
                    pasted_text = r_verify.stdout.decode("utf-8", errors="replace")
                except Exception as e:
                    _logger.warning(f"[Sender] pbpaste 验证读取异常: {e}")
                    pasted_text = ""

                # 4c. 判断验证结果
                is_match = (text in pasted_text) or (pasted_text.strip() == text.strip())
                _logger.info(f"[Sender] 验证结果: is_match={is_match}, 预期长度={len(text)}, 实际长度={len(pasted_text)}, 实际内容前缀='{pasted_text[:80]}...'")

                if is_match:
                    # 验证通过，先取消全选再按 return 发送
                    # 关键：verify 阶段用了 Command+A 全选，如果直接 return
                    # 某些输入框会把选中内容替换成换行符而不是发送
                    return_script = '''
                        tell application "System Events"
                            tell process "WeChat"
                                key code 124
                                delay 0.1
                                keystroke return
                            end tell
                        end tell
                    '''
                    r_return = subprocess.run(
                        ["osascript", "-e", return_script],
                        timeout=5,
                        capture_output=True,
                    )
                    _logger.info(f"[Sender] return 发送 returncode: {r_return.returncode}")
                    if r_return.returncode != 0:
                        err = r_return.stderr.decode("utf-8", errors="replace") if r_return.stderr else "unknown"
                        return ActionResult(success=False, error=f"回车发送失败: {err}")
                    _logger.info(f"[Sender] 发送成功, 文本长度: {len(text)}, 重试次数: {attempt}")
                    return ActionResult(success=True, sent_text=text)
                else:
                    _logger.warning(f"[Sender] paste 验证失败 (attempt {attempt+1}/{max_retries})")
                    if attempt < max_retries - 1:
                        # 清空输入框，重新复制文本到剪贴板，准备重试
                        clear_script = '''
                            tell application "System Events"
                                tell process "WeChat"
                                    keystroke "a" using command down
                                    delay 0.1
                                    key code 51
                                    delay 0.1
                                end tell
                            end tell
                        '''
                        r_clear = subprocess.run(
                            ["osascript", "-e", clear_script],
                            timeout=5,
                            capture_output=True,
                        )
                        _logger.info(f"[Sender] 清空输入框 returncode: {r_clear.returncode}")
                        # 重新复制到剪贴板
                        r_recopy = subprocess.run(
                            ["pbcopy"],
                            input=text.encode("utf-8"),
                            timeout=2,
                            capture_output=True,
                        )
                        _logger.info(f"[Sender] 重新复制剪贴板 returncode: {r_recopy.returncode}")
                        time.sleep(0.2)
                    else:
                        # 所有重试耗尽
                        return ActionResult(success=False, error=f"paste 验证失败，{max_retries} 次重试后输入框内容仍不匹配。最后一次读取到的内容: '{pasted_text[:100]}...'")
        except Exception as e:
            _logger.error(f"[Sender] 发送异常: {e}")
            return ActionResult(success=False, error=str(e))
        finally:
            # 5. 恢复用户原始剪贴板内容
            try:
                r_restore = subprocess.run(
                    ["pbcopy"],
                    input=original_clipboard.encode("utf-8"),
                    timeout=2,
                    capture_output=True,
                )
                _logger.info(f"[Sender] 恢复剪贴板 returncode: {r_restore.returncode}")
            except Exception as e:
                _logger.warning(f"[Sender] 恢复剪贴板异常: {e}")

    def send_image(self, image_path: str) -> ActionResult:
        """预留：将图片复制到剪贴板后 Command+V 粘贴发送。"""
        return ActionResult(
            success=False,
            error="send_image is not implemented yet",
        )

    def send_file(self, file_path: str) -> ActionResult:
        """预留：拖拽文件到输入框或复制到剪贴板后粘贴发送。"""
        return ActionResult(
            success=False,
            error="send_file is not implemented yet",
        )
