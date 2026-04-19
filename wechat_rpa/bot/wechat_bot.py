#!/usr/bin/env python3
"""L5 Bot Orchestrator - 主循环编排"""

import json
import re
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from wechat_rpa.models.base import ActionResult, PerceptionResult
from wechat_rpa.perception.vision_pipeline import VisionPipeline
from wechat_rpa.layout.profile import LayoutProfile
from wechat_rpa.session.chat_session import ChatSession
from wechat_rpa.reply.policy import ReplyPolicy
from wechat_rpa.reply.generator import ReplyGenerator
from wechat_rpa.action.message_sender import WeChatMessageSender
from wechat_rpa.action.chat_list_clicker import ChatListClicker
from wechat_rpa.logging.bot_logger import BotLogger, get_logger
from wechat_rpa.storage.message_store import MessageStore
from wechat_rpa.utils.debug_logger import DebugLogger


def _try_create_openclaw_client():
    """尝试创建 OpenClaw 客户端，失败时返回 None（使用兜底回复）"""
    try:
        from wechat_rpa.llm.openclaw_client import OpenClawClient
        return OpenClawClient.from_openclaw_config()
    except Exception:
        return None


def _normalize_chat_name(name: str) -> str:
    """对聊天名称进行 Unicode 归一化，防止 OCR 差异导致 session 分裂。
    
    注意：这里只做符号兼容性归一化（如半角括号→全角括号），
    不做业务启发式清洗（如数字前缀、噪声过滤）。
    那些应在 LayoutParser/Extractor 层解决。
    """
    # 统一括号
    name = name.replace("(", "（").replace(")", "）")
    # 统一引号
    name = name.replace('"', '"').replace('"', '"')
    name = name.replace("'", "'").replace("'", "'")
    # 统一破折号/连字符
    name = name.replace("—", "—").replace("–", "—")
    # 去掉首尾空格
    return name.strip()


class WeChatBot:
    def __init__(self, profile: LayoutProfile, on_message: Optional[Callable] = None, llm_client=None,
                 enable_chat_switch: bool = True, debug_mode: bool = False,
                 use_openclaw: bool = True):
        # Bot 层只依赖 VisionPipeline，禁止直接持有 Capture/OCR/Layout/Extractor
        self.perception = VisionPipeline(profile)
        self.sessions: Dict[str, ChatSession] = {}
        # 群聊必须被 @ 才回复（避免活跃群聊中的大量乱回）
        self.policy = ReplyPolicy(require_at_in_group=True)

        # LLM 客户端：优先使用传入的，其次尝试 OpenClaw，最后兜底
        if llm_client is not None:
            actual_llm = llm_client
        elif use_openclaw:
            actual_llm = _try_create_openclaw_client()
        else:
            actual_llm = None
        self.generator = ReplyGenerator(llm_client=actual_llm)
        self.sender = WeChatMessageSender()
        self.on_message = on_message  # 预留：外部系统集成回调
        self.logger: BotLogger = get_logger()
        self.message_store = MessageStore()
        self.running = False
        self._tick_id = 0
        self.enable_chat_switch = enable_chat_switch
        self.debug_mode = debug_mode
        # 免回复聊天列表：公众号、系统账号等不需要回复的聊天
        self.no_reply_chats = {"腾讯新闻", "文件传输助手"}
        self.debug_logger = DebugLogger()

        # Session 持久化
        self._session_file = Path("data/sessions.json")
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_sessions()

    def tick(self) -> None:
        """执行一轮: 感知 -> 去重 -> 决策 -> 回复/切换.

        流程:
        1. 感知: 截图 + OCR + 布局解析 + 消息提取
        2. 若 chat_name 为空: 不回复, 但尝试切换到未读聊天
        3. 会话去重: filter_new() 过滤已见过的消息
        4. 决策: 判断是否需要回复
        5. 回复: 生成并发送回复
        6. 切换: 若当前无消息或回复完成, 切换到其他未读聊天
        """
        self._tick_id += 1
        tick_id = self._tick_id
        self.logger.log_tick_start(tick_id, interval=5.0)
        result = None

        try:
            # 所有视觉细节对 Bot 隐藏，统一走 Pipeline
            result = self.perception.perceive()
            if result is None:
                self.logger.log_capture(tick_id, success=False, error="未能获取微信窗口画面，可能原因：微信未启动、窗口被最小化、或需要扫码登录")
                self.logger.warning(
                    "未能获取微信窗口画面，可能原因：微信未启动、窗口被最小化、或需要扫码登录"
                )
                return

            # 初始化调试日志：合并感知层的 debug_info
            if result.debug_info and isinstance(result.debug_info, dict):
                self.debug_logger.start_tick(tick_id, result.screenshot_path)
                for k, v in result.debug_info.items():
                    if hasattr(self.debug_logger.current, k):
                        # tick_id 和 bot_* 字段由 Bot 层管理，
                        # 感知层的默认值会覆盖正确值，必须排除
                        if k in ("tick_id",):
                            continue
                        if k.startswith("bot_"):
                            continue
                        setattr(self.debug_logger.current, k, v)

            # 保存截图到 data/screenshots/，方便后续排查
            if result.screenshot_path:
                try:
                    saved_path = self.message_store.save_screenshot(
                        result.screenshot_path, session_id=str(tick_id)
                    )
                    self.logger.debug(f"截图已保存: {saved_path}")
                    # 更新 screenshot_path 为保存后的路径，debug JSON 中记录真实位置
                    result.screenshot_path = str(saved_path)
                    if self.debug_logger.current is not None:
                        self.debug_logger.current.screenshot_path = str(saved_path)
                except Exception:
                    pass

            messages = result.messages
            chat_name = _normalize_chat_name(result.chat_name)
            if not chat_name:
                self.logger.warning("当前聊天名为空，可能未打开任何聊天窗口，跳过回复")
                if self.enable_chat_switch:
                    switch_target = self._try_switch_to_unread_chat(result)
                    if switch_target:
                        self.debug_logger.log_action(f"switch:{switch_target}")
                    else:
                        self.debug_logger.log_action("none", "聊天名为空且无未读")
                else:
                    self.debug_logger.log_action("none", "聊天名为空")
                return

            self.logger.log_layout(
                tick_id=tick_id,
                chat_name=chat_name,
                title_elem_count=0,
                input_elem_count=0,
                timestamp_elem_count=0,
                self_bubble_count=sum(1 for m in messages if m.sender_type.value == "self"),
                message_candidate_count=len(messages),
            )

            session = self._get_session(chat_name)
            new_messages = session.filter_new(messages)

            self.logger.log_messages(
                tick_id=tick_id,
                total_messages=len(messages),
                new_messages=len(new_messages),
                message_details=[
                    {"sender": m.sender, "sender_type": m.sender_type.value, "text": m.text}
                    for m in messages
                ],
            )

            if not new_messages:
                self.logger.log_decision(tick_id, should_reply=False, reason="无新消息", latest_text="")
                # 当前聊天为空/无消息，检查其他聊天是否有未读
                if self.enable_chat_switch:
                    switch_target = self._try_switch_to_unread_chat(result)
                    if switch_target:
                        self.debug_logger.log_action(f"switch:{switch_target}")
                    else:
                        self.debug_logger.log_action("none", "无未读或切换失败")
                else:
                    self.debug_logger.log_action("none", "切换已禁用")
                return

            # 推送新消息给外部系统（如 OpenClaw）
            for msg in new_messages:
                if self.on_message:
                    self.on_message(msg, session)

            # 从 new_messages 中倒序查找最后一条（即最新的）可回复的消息
            # 解决：当最新消息是 SYSTEM（如安全提示）时，前面的用户消息不应被忽略
            latest = None
            should_send = False
            for msg in reversed(new_messages):
                if self.policy.should_reply(msg, session):
                    latest = msg
                    should_send = True
                    break

            # 免回复聊天：公众号/系统账号等，直接跳过回复并切换
            if should_send and chat_name in self.no_reply_chats:
                self.logger.log_decision(
                    tick_id, should_reply=False,
                    reason=f"当前聊天 '{chat_name}' 在免回复列表中（公众号/系统账号）",
                    latest_text=latest.text if latest else ""
                )
                self.debug_logger.log_bot_decision(
                    chat_name=chat_name,
                    new_messages_count=len(new_messages),
                    should_reply=False,
                    switch_reason="免回复聊天",
                )
                if self.enable_chat_switch:
                    switch_target = self._try_switch_to_unread_chat(result)
                    if switch_target:
                        self.debug_logger.log_action(f"switch:{switch_target}")
                    else:
                        self.debug_logger.log_action("none")
                else:
                    self.debug_logger.log_action("none")
                return

            if not should_send:
                skip_reason = "无符合条件的消息可回复"
                if new_messages:
                    last = new_messages[-1]
                    skip_reason = f"最新消息 sender={last.sender_type.value}, 且前方无 OTHER 消息可回复"
                self.logger.log_decision(
                    tick_id, should_reply=False,
                    reason=skip_reason,
                    latest_text=new_messages[-1].text if new_messages else ""
                )
                self.debug_logger.log_bot_decision(
                    chat_name=chat_name,
                    new_messages_count=len(new_messages),
                    should_reply=False,
                    switch_reason=skip_reason,
                )
                # 当前聊天无需回复，检查其他聊天是否有未读
                if self.enable_chat_switch:
                    switch_target = self._try_switch_to_unread_chat(result)
                    if switch_target:
                        self.debug_logger.log_action(f"switch:{switch_target}")
                    else:
                        self.debug_logger.log_action("none")
                else:
                    self.debug_logger.log_action("none")
                return

            reply = self.generator.generate(latest, session)
            self.logger.log_decision(
                tick_id, should_reply=True,
                reason=f"触发回复条件 (从 {len(new_messages)} 条新消息中选取)",
                latest_text=latest.text, reply_text=reply
            )
            self.debug_logger.log_bot_decision(
                chat_name=chat_name,
                new_messages_count=len(new_messages),
                should_reply=True,
                reply_target=latest.text if latest else "",
                reply_text=reply,
            )

            if reply:
                action_result = self.sender.send(reply)
                if action_result.success:
                    session.record_sent(reply)
                    self.logger.log_send(tick_id, success=True, text=reply)
                    self.debug_logger.log_action(f"send:{reply}")
                else:
                    self.logger.log_send(tick_id, success=False, text=reply, error=action_result.error)
                    self.debug_logger.log_action("none", f"发送失败: {action_result.error}")
                # 回复完成后，如果有其他未读聊天，继续切换
                if self.enable_chat_switch:
                    switch_target = self._try_switch_to_unread_chat(result)
                    if switch_target:
                        self.debug_logger.log_action(f"switch:{switch_target}")
                return

        except Exception as exc:
            self.logger.log_exception(tick_id, phase="tick", exc=exc)
            if self.debug_logger.current:
                self.debug_logger.log_action("none", f"异常: {exc}")
            # 重新抛出以便上层也能感知
            raise
        finally:
            if self.debug_logger.current is not None:
                try:
                    path = self.debug_logger.save()
                    self.logger.debug(f"调试日志已保存: {path}")
                except Exception:
                    pass
                self.debug_logger.current = None
            # 每 10 个 tick 自动保存 session 状态
            if self._tick_id % 10 == 0:
                self.save_sessions()

    def _load_sessions(self) -> None:
        """从磁盘加载 session 状态，防止重启后重复回复。"""
        if not self._session_file.exists():
            return
        try:
            with open(self._session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for chat_name, session_data in data.items():
                self.sessions[chat_name] = ChatSession.from_dict(session_data)
            self.logger.info(f"📚 已加载 {len(self.sessions)} 个会话状态")
        except Exception as e:
            self.logger.warning(f"加载 session 状态失败: {e}")

    def save_sessions(self) -> None:
        """保存 session 状态到磁盘。"""
        try:
            data = {
                name: session.to_dict()
                for name, session in self.sessions.items()
            }
            with open(self._session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"💾 已保存 {len(self.sessions)} 个会话状态")
        except Exception as e:
            self.logger.warning(f"保存 session 状态失败: {e}")

    def _try_switch_to_unread_chat(self, result: PerceptionResult) -> str:
        """
        检查左侧列表中是否有未读聊天，如有则点击切换。

        触发场景：
        1. 当前 chat_name 为空（右侧未打开聊天）
        2. 当前无新消息可回复
        3. 回复完成后，继续处理其他未读

        返回切换目标的昵称（未切换则返回空字符串）。
        """
        chat_list_items = result.chat_list_items
        if not chat_list_items:
            self.debug_logger.log_bot_decision(switch_reason="chat_list_items 为空")
            return ""

        # 过滤出有未读的项（昵称统一归一化后比较）
        current_chat = _normalize_chat_name(result.chat_name)
        unread_items = [
            item for item in chat_list_items
            if item.unread_count
            and _normalize_chat_name(item.nickname) != current_chat
            and _normalize_chat_name(item.nickname) not in {
                _normalize_chat_name(c) for c in self.no_reply_chats
            }
        ]
        if not unread_items:
            self.debug_logger.log_bot_decision(
                switch_reason=f"无未读项 (chat_list={len(chat_list_items)}, current={current_chat})"
            )
            return ""

        # 优先选择未读数最多的
        unread_items.sort(key=lambda item: int(item.unread_count) if item.unread_count.isdigit() else 0, reverse=True)
        target = unread_items[0]

        # 使用感知结果中的窗口坐标
        window_rect = result.window_rect
        scale_factor = result.scale_factor
        if window_rect is None:
            self.logger.warning("感知结果缺少窗口坐标，跳过聊天切换")
            self.debug_logger.log_bot_decision(switch_reason="缺少窗口坐标")
            return ""

        clicker = ChatListClicker(window_rect, scale_factor)
        clicked = clicker.click_item(target)
        if clicked:
            self.logger.info(
                f"🔄 切换聊天: {target.nickname!r} (未读 {target.unread_count})"
            )
            self.debug_logger.log_bot_decision(
                switch_target=target.nickname,
                switch_reason=f"未读 {target.unread_count}",
            )
            # Debug 模式：截图验证切换是否成功
            if self.debug_mode:
                time.sleep(0.8)
                verify_result = self.perception.perceive()
                if verify_result is not None:
                    actual_chat = _normalize_chat_name(verify_result.chat_name)
                    expected_chat = _normalize_chat_name(target.nickname)
                    if actual_chat != expected_chat:
                        self.logger.warning(
                            f"❌ 切换验证失败: 期望 '{expected_chat}', 实际 '{actual_chat}'"
                        )
                        # 保存验证失败的截图用于排查
                        if verify_result.screenshot_path:
                            try:
                                saved = self.message_store.save_screenshot(
                                    verify_result.screenshot_path,
                                    session_id=f"verify_fail_{target.nickname}"
                                )
                                self.logger.info(f"验证失败截图已保存: {saved}")
                            except Exception:
                                pass
                    else:
                        self.logger.info(f"✅ 切换验证成功: '{actual_chat}'")
            return target.nickname
        else:
            self.logger.warning(f"❌ 切换聊天失败: {target.nickname!r}")
            self.debug_logger.log_bot_decision(switch_reason=f"点击失败: {target.nickname}")
            return ""

    def run_auto(self, interval: float = 5.0) -> None:
        """自动运行主循环"""
        self.running = True
        while self.running:
            try:
                self.tick()
            except Exception as e:
                self.logger.error(f"Tick #{self._tick_id} 未捕获异常: {e}", exc_info=True)
            time.sleep(interval)

    def _get_session(self, chat_name: str) -> ChatSession:
        """获取或创建指定聊天的会话对象。chat_name 会先进行 Unicode 归一化。"""
        normalized = _normalize_chat_name(chat_name)
        if normalized not in self.sessions:
            chat_id = f"chat_{len(self.sessions)}"
            self.sessions[normalized] = ChatSession(chat_id=chat_id, chat_name=normalized)
        return self.sessions[normalized]

    def send_to_chat(self, chat_name: str, text: str) -> ActionResult:
        """外部系统调用此接口主动发消息到指定聊天。"""
        # 当前实现直接发送，未来可扩展为：点击聊天列表 -> 感知 -> 发送
        result = self.sender.send(text)
        if result.success:
            session = self._get_session(chat_name)
            session.record_sent(text)
        return result
