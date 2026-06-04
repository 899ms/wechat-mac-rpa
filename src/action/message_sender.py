#!/usr/bin/env python3
"""L4 Action Layer - Message Sender

负责发送消息到微信窗口。
"""

import logging
import os
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
    """基于 AppleScript 的微信消息发送器

    安全改进（2026-05-16）：
    1. 每次重试都从头开始（重新激活 + focus + pbcopy），避免窗口焦点丢失后后续重试白给。
    2. 粘贴前验证 WeChat 是 frontmost 进程，防止消息发到其他应用。
    3. 异常内容熔断：verify 读到的内容长度超过预期 3 倍时立即中止，防止误删/误发其他窗口内容。

    静默模式（2026-05-29）：
    - silent_mode=True 时不实际发送消息，只生成回复并记录日志
    - 用于数据收集、实验、调试，避免打扰用户
    """

    def __init__(self, silent_mode: bool = False):
        self.silent_mode = silent_mode
        # 白名单：静默模式下仍然实际发送的聊天（逗号分隔的聊天名）
        raw = os.environ.get("SILENT_WHITELIST", "")
        self._silent_whitelist = {n.strip() for n in raw.split(",") if n.strip()}

    # ------------------------------------------------------------------
    # 原子操作辅助方法
    # ------------------------------------------------------------------

    def _ensure_wechat_frontmost(self, max_retries: int = 3) -> tuple[bool, str]:
        """确保 WeChat 是当前 frontmost 进程，如果不是则重试激活。"""
        front_app = "unknown"
        for attempt in range(max_retries):
            script = '''
                tell application "System Events"
                    tell process "WeChat"
                        set frontmost to true
                    end tell
                    delay 0.3
                    set frontApp to name of first application process whose frontmost is true
                    return frontApp
                end tell
            '''
            try:
                r = subprocess.run(
                    ["osascript", "-e", script],
                    timeout=5,
                    capture_output=True,
                )
                if r.returncode == 0:
                    front_app = r.stdout.decode("utf-8", errors="replace").strip()
                    if front_app == "WeChat":
                        _logger.info(f"[Sender] 窗口激活验证通过 (attempt {attempt + 1}/{max_retries})")
                        return True, ""
                    else:
                        _logger.warning(
                            f"[Sender] frontmost 应用是 '{front_app}'，不是 WeChat "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                else:
                    err = r.stderr.decode("utf-8", errors="replace")[:200]
                    _logger.warning(f"[Sender] 查询 frontmost 失败: {err} (attempt {attempt + 1}/{max_retries})")
            except subprocess.TimeoutExpired:
                _logger.warning(f"[Sender] 窗口激活验证超时 (attempt {attempt + 1}/{max_retries})")
            except Exception as e:
                _logger.warning(f"[Sender] 窗口激活验证异常: {e} (attempt {attempt + 1}/{max_retries})")

            if attempt < max_retries - 1:
                time.sleep(0.3)

        return False, f"无法将 WeChat 设为 frontmost，最后查询到的应用: {front_app}"

    def _focus_input(self) -> tuple[int, str]:
        """点击微信窗口底部中央（输入框大致位置）获取焦点。"""
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
        r = subprocess.run(["osascript", "-e", focus_script], timeout=5, capture_output=True)
        err = r.stderr.decode("utf-8", errors="replace")[:200] if r.stderr else ""
        _logger.info(f"[Sender] focus脚本 returncode: {r.returncode}, stderr: {err}")
        return r.returncode, err

    def _pbcopy(self, text: str) -> tuple[int, str]:
        """将文本复制到剪贴板。"""
        r = subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            timeout=2,
            capture_output=True,
        )
        err = r.stderr.decode("utf-8", errors="replace")[:200] if r.stderr else ""
        _logger.info(f"[Sender] pbcopy returncode: {r.returncode}, stderr: {err}")
        return r.returncode, err

    def _paste(self, delay: float) -> tuple[int, str]:
        """执行 AppleScript Command+V 粘贴。"""
        paste_script = f'''
            tell application "System Events"
                tell process "WeChat"
                    keystroke "v" using command down
                    delay {delay}
                end tell
            end tell
        '''
        r = subprocess.run(
            ["osascript", "-e", paste_script],
            timeout=5,
            capture_output=True,
        )
        err = r.stderr.decode("utf-8", errors="replace")[:200] if r.stderr else ""
        _logger.info(f"[Sender] paste returncode: {r.returncode}, delay={delay}s")
        return r.returncode, err

    def _clear_clipboard(self) -> None:
        """清空剪贴板，防止 verify 读到旧内容。"""
        try:
            subprocess.run(["pbcopy"], input=b"", timeout=2, capture_output=True)
        except Exception as e:
            _logger.debug("[Sender] 清空剪贴板失败: %s", e)

    def _verify(self) -> tuple[str, int, int]:
        """验证输入框内容：Command+A + Command+C + pbpaste。
        返回 (pasted_text, verify_script_rc, pbpaste_rc)。
        """
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
        verify_rc = r_verify_script.returncode

        try:
            r_paste = subprocess.run(
                ["pbpaste"],
                timeout=2,
                capture_output=True,
            )
            pasted_text = r_paste.stdout.decode("utf-8", errors="replace")
            pbpaste_rc = r_paste.returncode
        except Exception as e:
            _logger.warning(f"[Sender] pbpaste 验证读取异常: {e}")
            pasted_text = ""
            pbpaste_rc = -1

        _logger.info(
            f"[Sender] verify: len={len(pasted_text)}, verify_rc={verify_rc}, "
            f"pbpaste_rc={pbpaste_rc}, raw_repr={repr(pasted_text[:120])}"
        )
        return pasted_text, verify_rc, pbpaste_rc

    def _clear_input(self) -> None:
        """清空微信输入框内容。"""
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
        r = subprocess.run(
            ["osascript", "-e", clear_script],
            timeout=5,
            capture_output=True,
        )
        _logger.info(f"[Sender] 清空输入框 returncode: {r.returncode}")

    def _keystroke(self, text: str) -> tuple[int, str]:
        """通过 AppleScript keystroke 逐字输入文本。"""
        escaped = text.replace('"', '\\"')
        ks_script = f'''
            tell application "System Events"
                tell process "WeChat"
                    keystroke "{escaped}"
                    delay 0.5
                end tell
            end tell
        '''
        r = subprocess.run(
            ["osascript", "-e", ks_script],
            timeout=10,
            capture_output=True,
        )
        err = r.stderr.decode("utf-8", errors="replace")[:200] if r.stderr else ""
        _logger.info(f"[Sender] keystroke returncode: {r.returncode}, stderr: {err}")
        return r.returncode, err

    def _send_return(self) -> tuple[int, str]:
        """按 Return 键发送消息（先取消全选避免替换为换行）。"""
        return_script = '''
            tell application "System Events"
                tell process "WeChat"
                    key code 124
                    delay 0.1
                    keystroke return
                end tell
            end tell
        '''
        r = subprocess.run(
            ["osascript", "-e", return_script],
            timeout=5,
            capture_output=True,
        )
        err = r.stderr.decode("utf-8", errors="replace")[:200] if r.stderr else ""
        _logger.info(f"[Sender] return 发送 returncode: {r.returncode}")
        return r.returncode, err

    # ------------------------------------------------------------------
    # 主发送方法
    # ------------------------------------------------------------------

    def send(self, text: str, chat_name: str = "") -> ActionResult:
        """发送文本消息到当前微信聊天。

        静默模式下不实际发送，只记录日志并返回模拟成功。
        白名单内的聊天在静默模式下仍然实际发送。
        """
        if self.silent_mode:
            if chat_name and chat_name in self._silent_whitelist:
                _logger.info(f"[Sender] 白名单聊天 '{chat_name}' 跳过静默，实际发送")
            else:
                _logger.info(f"[Sender] [SILENT] 静默模式跳过发送, 文本长度: {len(text)} 字符, 内容: {text[:80]}...")
                return ActionResult(success=True, sent_text=text)

        t_send_start = time.time()
        perf = {}

        # 保存用户原始剪贴板内容（尽力恢复文本内容）
        original_clipboard = ""
        t0 = time.time()
        try:
            r_clip = subprocess.run(
                ["pbpaste"],
                timeout=2,
                capture_output=True,
            )
            if r_clip.returncode == 0:
                original_clipboard = r_clip.stdout.decode("utf-8", errors="replace")
            perf["read_clipboard"] = (time.time() - t0) * 1000
        except Exception as e:
            _logger.warning(f"[Sender] 读取原始剪贴板异常: {e}")
            perf["read_clipboard"] = 0

        _logger.info(
            f"[Sender] 开始发送, 文本长度: {len(text)} 字符, "
            f"原始剪贴板长度: {len(original_clipboard)} 字符"
        )

        def _try_once(delay: float, label: str) -> tuple[bool, str, str]:
            """执行一次完整的 激活→focus→pbcopy→paste→verify 流程。

            返回 (is_match, pasted_text, error_or_info)
            error_or_info 为空字符串表示流程正常执行到了 verify。
            """
            # 1. 确保 frontmost
            ok, err = self._ensure_wechat_frontmost()
            if not ok:
                return False, "", err

            # 2. focus 输入框
            rc, err = self._focus_input()
            if rc != 0:
                return False, "", f"focus 失败: {err}"

            # 3. pbcopy
            rc, err = self._pbcopy(text)
            if rc != 0:
                return False, "", f"pbcopy 失败: {err}"

            # 4. paste
            rc, err = self._paste(delay)
            if rc != 0:
                return False, "", f"paste 失败: {err}"

            # 5. 清空剪贴板（确保 verify 读的是输入框内容）
            self._clear_clipboard()
            time.sleep(0.15)

            # 6. verify
            pasted_text, verify_rc, pbpaste_rc = self._verify()

            # 7. 异常内容熔断：焦点可能在错误窗口
            if len(pasted_text) > len(text) * 3:
                _logger.error(
                    f"[Sender] {label} 异常内容熔断: "
                    f"实际长度 {len(pasted_text)} >> 预期 {len(text)}, "
                    f"raw_repr={repr(pasted_text[:200])}"
                )
                return (
                    False,
                    pasted_text,
                    f"异常内容熔断（长度 {len(pasted_text)}，预期 {len(text)}）",
                )

            # 8. 匹配判断
            is_match = (text in pasted_text) or (pasted_text.strip() == text.strip())
            _logger.info(
                f"[Sender] {label} 结果: is_match={is_match}, "
                f"预期长度={len(text)}, 实际长度={len(pasted_text)}"
            )
            return is_match, pasted_text, ""

        try:
            # 主重试循环：每次失败都从头开始
            for attempt in range(3):
                delay = 0.3 if attempt < 2 else 0.8
                label = f"attempt {attempt + 1}/3"
                is_match, pasted_text, err = _try_once(delay, label)

                if is_match:
                    rc, err = self._send_return()
                    if rc == 0:
                        t_total_ms = (time.time() - t_send_start) * 1000
                        _logger.info(
                            f"[Perf][Sender] total={t_total_ms:.0f}ms "
                            f"read_clipboard={perf.get('read_clipboard', 0):.0f}ms "
                            f"attempt={attempt}"
                        )
                        _logger.info(
                            f"[Sender] 发送成功, 文本长度: {len(text)}, "
                            f"重试次数: {attempt}"
                        )
                        return ActionResult(success=True, sent_text=text)
                    else:
                        return ActionResult(
                            success=False, error=f"回车发送失败: {err}"
                        )

                # 不是最后一次：如果流程正常走到了 verify（err 为空），先清空输入框
                if attempt < 2 and err == "":
                    _logger.warning(
                        f"[Sender] {label} 失败，清空输入框后从头重试"
                    )
                    self._clear_input()
                    time.sleep(0.2)

            # fallback 1: 更长 delay
            _logger.warning(
                "[Sender] 3 次常规重试均失败，尝试 fallback paste (delay=1.0s)"
            )
            is_match, pasted_text, err = _try_once(1.0, "fallback paste")
            if is_match:
                rc, err = self._send_return()
                if rc == 0:
                    _logger.info("[Sender] fallback paste 发送成功")
                    return ActionResult(success=True, sent_text=text)

            # fallback 2: keystroke 逐字输入
            _logger.warning(
                "[Sender] fallback paste 仍失败，尝试 keystroke 逐字输入"
            )
            ok, err = self._ensure_wechat_frontmost()
            if ok:
                self._focus_input()
                self._clear_input()
                rc, err = self._keystroke(text)
                if rc == 0:
                    self._clear_clipboard()
                    time.sleep(0.15)
                    pasted_text, _, _ = self._verify()
                    is_match = (text in pasted_text) or (
                        pasted_text.strip() == text.strip()
                    )
                    _logger.info(
                        f"[Sender] keystroke verify: is_match={is_match}, "
                        f"raw_repr={repr(pasted_text[:120])}"
                    )
                    if is_match:
                        rc2, err2 = self._send_return()
                        if rc2 == 0:
                            _logger.info("[Sender] keystroke 发送成功")
                            return ActionResult(success=True, sent_text=text)

            # 全部失败
            return ActionResult(
                success=False,
                error=(
                    f"发送失败，3 次重试+fallback 后仍不匹配。"
                    f"最后信息: {err or repr(pasted_text[:200])}"
                ),
            )

        except Exception as e:
            _logger.error(f"[Sender] 发送异常: {e}")
            return ActionResult(success=False, error=str(e))
        finally:
            # 恢复用户原始剪贴板内容
            try:
                r_restore = subprocess.run(
                    ["pbcopy"],
                    input=original_clipboard.encode("utf-8"),
                    timeout=2,
                    capture_output=True,
                )
                _logger.info(
                    f"[Sender] 恢复剪贴板 returncode: {r_restore.returncode}"
                )
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
