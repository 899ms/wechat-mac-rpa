#!/usr/bin/env python3
"""L5 Bot Orchestrator - 主循环编排"""

import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from src.models.base import ActionResult, ChatMessage, PerceptionResult, SenderType
from src.perception.vision_pipeline import VisionPipeline
from src.layout.profile import LayoutProfile
from src.session.global_store import GlobalStore
from src.reply.policy import ReplyPolicy
from src.utils.chat_utils import _is_group_chat_name, _normalize_chat_name
from src.reply.generator import ReplyGenerator
from src.action.message_sender import WeChatMessageSender
from src.action.chat_list_clicker import ChatListClicker
from src.logging.bot_logger import BotLogger, get_logger
from src.utils.debug_logger import DebugLogger
from src.memory import MemoryEngine


def _try_create_openclaw_client():
    """尝试创建 OpenClaw 客户端，失败时返回 None（退化为单模型模式）"""
    try:
        from src.llm.openclaw_client import OpenClawClient
        return OpenClawClient.from_openclaw_config()
    except Exception:
        return None


class WeChatBot:
    def __init__(self, profile: LayoutProfile, on_message: Optional[Callable] = None, llm_client=None,
                 complex_llm_client=None, debug_mode: bool = False, use_openclaw: bool = True, perception=None,
                 enable_chat_switch: bool = True):
        if perception is not None:
            self.perception = perception
        else:
            self.perception = VisionPipeline(profile)
        self.global_store = GlobalStore()
        self.policy = ReplyPolicy(require_at_in_group=False)

        if llm_client is not None:
            actual_llm = llm_client
        elif use_openclaw:
            actual_llm = _try_create_openclaw_client()
        else:
            actual_llm = None

        # 启动时自动同步 knowledge_source.md → JSON / wiki
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from scripts.sync_knowledge import sync
            if sync():
                print("[knowledge] 已自动同步 knowledge_source.md")
        except Exception:
            pass

        # 先创建记忆引擎（ReplyGenerator 初始化时需要）
        self.memory_engine: MemoryEngine = MemoryEngine(llm_client=actual_llm)
        # 再创建 Generator，把 memory_engine 直接传入（这样 search_memory 工具才能注册）
        self.generator = ReplyGenerator(llm_client=actual_llm, complex_llm_client=complex_llm_client, memory_engine=self.memory_engine)
        self.sender = WeChatMessageSender()
        self.on_message = on_message
        self.logger: BotLogger = get_logger()
        self.running = False
        self._tick_id = 0
        self.debug_mode = debug_mode
        self.debug_logger = DebugLogger()
        # 免回复聊天列表：公众号、系统账号等不需要回复的聊天
        self.no_reply_chats = {"腾讯新闻", "文件传输助手"}

        # 切换聊天防抖：10 秒内不重复切换同一个目标
        self._last_switch_target: str = ""
        self._last_switch_time: float = 0.0
        self._switch_debounce_seconds: float = 10.0

        # 全局状态持久化目录
        Path("data").mkdir(parents=True, exist_ok=True)

        # ===== WeFlow 全量初始化 =====
        self._weflow_mode = os.getenv("WEFLOW_MODE", "ocr")
        print(f"[WeFlow] 模式检测: WEFLOW_MODE={self._weflow_mode}")
        if self._weflow_mode in ("weflow", "hybrid"):
            try:
                from src.perception.weflow_pipeline import WeFlowPipeline
                has_wf = hasattr(self.perception, '_weflow_pipeline')
                wf_val = getattr(self.perception, '_weflow_pipeline', None)
                print(f"[WeFlow] pipeline检查: hasattr={has_wf}, value={wf_val}")
                if has_wf and wf_val:
                    weflow = wf_val
                    init_ok = weflow.initialize()
                    print(f"[WeFlow] initialize() 返回: {init_ok}")
                    if init_ok:
                        self._inject_weflow_history(weflow)
                        print(f"[WeFlow] 全量初始化完成: {weflow.init_total_messages} 条消息")
                        # 历史注入完成后，切回 OCR 模式运行，不再依赖 WeFlow API
                        self._weflow_mode = "ocr"
                        # 同步修改 perception 层的模式，确保后续 tick 不走 WeFlow
                        perception = getattr(self, 'perception', None)
                        if perception and hasattr(perception, '_weflow_mode'):
                            perception._weflow_mode = "ocr"
                            print("[WeFlow] 历史注入完成，perception 层已切换为 OCR 模式")
                        else:
                            print("[WeFlow] 历史注入完成，后续切换为 OCR 模式运行")
                    else:
                        print(f"[WeFlow] 初始化失败: {weflow.get_init_status().get('error')}")
                else:
                    print("[WeFlow] perception 中没有 _weflow_pipeline，跳过历史注入")
            except Exception as e:
                print(f"[WeFlow] 启动初始化异常: {e}")
                import traceback
                traceback.print_exc()
                self._weflow_mode = "ocr"

    def _inject_weflow_history(self, weflow_pipeline) -> None:
        """将 WeFlow 全量历史注入 GlobalStore。"""
        try:
            history_map = weflow_pipeline.export_all_history()
            total = 0
            for talker, messages in history_map.items():
                if not messages:
                    continue
                # 用第一条消息的 chat_name 作为 key
                chat_name = messages[0].chat_name or talker
                is_group = _is_group_chat_name(chat_name)
                injected = self.global_store.inject_history(chat_name, messages, mode="weflow", is_group=is_group)
                total += injected
            print(f"[WeFlow] 历史注入完成: {total} 条消息注入 GlobalStore")
        except Exception as e:
            print(f"[WeFlow] 历史注入失败: {e}")

    def tick(self) -> None:
        """执行一轮: 感知 -> 去重 -> 决策 -> 回复."""
        self._tick_id += 1
        tick_id = self._tick_id
        self.logger.log_tick_start(tick_id, interval=getattr(self, '_interval', 5.0))
        result = None

        # 在 tick 一开始就初始化调试日志，即使 perceive() 失败也有记录
        self.debug_logger.start_tick(tick_id, "")

        try:
            result = self.perception.perceive()
            if result is None:
                self.logger.log_capture(tick_id, success=False, error="未能获取微信窗口画面，可能原因：微信未启动、窗口被最小化、或需要扫码登录")
                self.logger.warning(
                    "未能获取微信窗口画面，可能原因：微信未启动、窗口被最小化、或需要扫码登录"
                )
                self.debug_logger.log_action("none", action_input="", success=False, error="perceive 返回 None")
                return

            # 记录 Perception 层输出
            if self.debug_logger.current is not None:
                self.debug_logger.current.screenshot_path = result.screenshot_path or ""
                self.debug_logger.log_perception_output(
                    chat_name=result.chat_name,
                    messages_count=len(result.messages),
                    chat_list_count=len(result.chat_list_items),
                )
            # 复制 SmartPipeline 的 debug_info（OCR/Layout/API 中间结果）
            if result.debug_info and isinstance(result.debug_info, dict):
                for k, v in result.debug_info.items():
                    if hasattr(self.debug_logger.current, k):
                        if k in ("tick_id",):
                            continue
                        if k.startswith("bot_"):
                            continue
                        if k.startswith("session_"):
                            continue
                        if k.startswith("action_"):
                            continue
                        setattr(self.debug_logger.current, k, v)

            if result.screenshot_path:
                try:
                    saved_path = self.global_store.save_screenshot(
                        result.screenshot_path, session_id=str(tick_id)
                    )
                    self.logger.debug(f"截图已保存: {saved_path}")
                    result.screenshot_path = str(saved_path)
                    if self.debug_logger.current is not None:
                        self.debug_logger.current.screenshot_path = str(saved_path)
                except Exception:
                    pass

            messages = result.messages
            raw_chat_name = result.chat_name or ""
            chat_name = _normalize_chat_name(raw_chat_name)
            is_group = _is_group_chat_name(raw_chat_name)

            if not chat_name:
                if messages:
                    # 右侧有消息但标题栏 OCR 失败，不切换避免误点当前聊天
                    self.logger.warning("当前聊天名为空但检测到消息，标题栏识别失败，跳过切换避免误点")
                    self.debug_logger.log_action("none", action_input="", success=False, error="标题栏识别失败，跳过避免误点")
                else:
                    self.logger.warning("当前聊天名为空且无消息，可能未打开任何聊天窗口，尝试切换到未读")
                    switch_target = self._try_switch_to_unread_chat(result)
                    if switch_target:
                        self.debug_logger.log_action("switch", action_input=switch_target, success=True)
                    else:
                        self.debug_logger.log_action("none", action_input="", success=False, error="聊天名为空且无未读")
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

            state, unreplied = self.global_store.merge_tick(
                chat_name, messages, mode=self._weflow_mode, is_group=is_group
            )

            # 记录 Session 层输入输出
            msg_dicts = [
                {
                    "sender": m.sender,
                    "sender_type": m.sender_type.value,
                    "text": m.text,
                    "type": m.message_type,
                    "image_desc": m.image_description,
                    "image_dup": m.is_image_duplicate,
                    "replied": m.replied,
                }
                for m in messages
            ]
            unreplied_dicts = [
                {
                    "sender": m.sender,
                    "sender_type": m.sender_type.value,
                    "text": m.text,
                    "type": m.message_type,
                    "image_desc": m.image_description,
                    "image_dup": m.is_image_duplicate,
                    "replied": m.replied,
                }
                for m in unreplied
            ]
            try:
                total_stored = len(state.messages)
            except (TypeError, AttributeError):
                total_stored = 0
            self.debug_logger.log_session(
                input_chat_name=chat_name,
                input_messages=msg_dicts,
                output_unreplied=unreplied_dicts,
                total_stored=total_stored,
            )

            self.logger.log_messages(
                tick_id=tick_id,
                total_messages=len(messages),
                new_messages=len(unreplied),
                message_details=msg_dicts,
            )

            if not unreplied:
                self.logger.log_decision(tick_id, should_reply=False, reason="无未回复消息", latest_text="")
                self.debug_logger.log_action("none", action_input="", success=False, error="无未回复消息")
                # 当前聊天无未回复消息，尝试切换到其他未读聊天
                switch_target = self._try_switch_to_unread_chat(result)
                if switch_target:
                    self.debug_logger.log_action(f"switch:{switch_target}")
                return

            for msg in unreplied:
                if self.on_message:
                    self.on_message(msg, state)

            latest = None
            should_send = False
            for msg in reversed(unreplied):
                if self.policy.should_reply(msg, state):
                    latest = msg
                    should_send = True
                    break

            # 收集所有需要回复的未读消息
            to_reply = [msg for msg in unreplied if self.policy.should_reply(msg, state)]
            if not to_reply:
                skip_reason = "无符合条件的消息可回复"
                self.logger.log_decision(
                    tick_id, should_reply=False,
                    reason=skip_reason,
                    latest_text=unreplied[-1].text if unreplied else ""
                )
                self.debug_logger.log_bot_decision(
                    chat_name=chat_name,
                    new_messages_count=len(unreplied),
                    should_reply=False,
                    switch_reason=skip_reason,
                )
                self.debug_logger.log_action("none", action_input="", success=False, error=skip_reason)
                return

            # 传递完整消息上下文 + 所有未读消息，让 AI 生成多条回复
            all_messages = getattr(state, "messages", [])
            if not isinstance(all_messages, list):
                all_messages = []
            replies = self.generator.generate(to_reply, all_messages, is_group=is_group, tick_id=tick_id)
            reply_text = " | ".join(replies) if replies else ""
            self.logger.log_decision(
                tick_id, should_reply=True,
                reason=f"触发回复条件 (未读 {len(unreplied)} 条，需回复 {len(to_reply)} 条，生成 {len(replies)} 条回复)",
                latest_text=unreplied[-1].text, reply_text=reply_text
            )
            # 记录 LLM 回复生成的完整链路（含多轮调用 + 工具调用）
            if self.debug_logger.current is not None:
                self.debug_logger.log_reply_generation(
                    system_prompt=getattr(self.generator, 'last_system_prompt', ''),
                    user_prompt=getattr(self.generator, 'last_user_prompt', ''),
                    raw_response=getattr(self.generator, 'last_raw_response', ''),
                    llm_calls=getattr(self.generator, 'last_llm_calls', []),
                    tool_calls=getattr(self.generator, 'last_tool_calls', []),
                    trace=getattr(self.generator, 'last_generation_trace', []),
                    loaded_skills=getattr(self.generator, 'last_loaded_skills', []),
                    skill_injected_content=getattr(self.generator, 'last_skill_injected_content', ''),
                    active_llm=getattr(self.generator, 'last_active_llm', ''),
                    hermes_fallback_triggered=getattr(self.generator, 'last_hermes_fallback_triggered', False),
                    hermes_messages=getattr(self.generator, 'last_hermes_messages', []),
                    hermes_response=getattr(self.generator, 'last_hermes_response', ''),
                )
            self.debug_logger.log_bot_decision(
                chat_name=chat_name,
                new_messages_count=len(unreplied),
                should_reply=True,
                reply_target=unreplied[-1].text if unreplied else "",
                reply_text=reply_text,
            )

            if not replies:
                self.debug_logger.log_action("none", action_input="", success=False, error="所有消息都跳过")
                # 即使不回复，也标记为已处理，避免下一轮又当成未读
                for msg in to_reply:
                    self.global_store.mark_replied(chat_name, msg, "(未回复)")
                return

            # 免回复聊天：跳过回复，尝试切换到其他未读聊天
            if chat_name in self.no_reply_chats:
                self.logger.log_decision(
                    tick_id, should_reply=False,
                    reason=f"当前聊天 '{chat_name}' 在免回复列表中",
                    latest_text=unreplied[-1].text if unreplied else ""
                )
                self.debug_logger.log_action("none", action_input=reply_text, success=False, error="免回复聊天")
                switch_target = self._try_switch_to_unread_chat(result)
                if switch_target:
                    self.debug_logger.log_action("switch", action_input=switch_target, success=True)
                return

            # 逐条发送回复，间隔 1.5 秒
            for i, reply in enumerate(replies):
                action_result = self.sender.send(reply)
                if action_result.success:
                    self.logger.log_send(tick_id, success=True, text=reply)
                    self.debug_logger.log_action("send", action_input=reply, success=True)
                    # Bot 自己发的消息不直接进 history，放入 pending 等感知层确认
                    self_msg = ChatMessage(
                        text=reply, sender="bot", sender_type=SenderType.SELF,
                        chat_name=chat_name, replied=True, reply_text=reply,
                        reply_time=time.time(), message_type="text"
                    )
                    state = self.global_store.chats.get(chat_name)
                    if state is not None:
                        state.pending_self_messages.append(self_msg)
                        self.logger.info("[Pending] %s 记录 pending self 消息 (pending 队列长度=%d): %.60s",
                                             chat_name, len(state.pending_self_messages), reply)
                else:
                    self.logger.log_send(tick_id, success=False, text=reply, error=action_result.error)
                    self.debug_logger.log_action("send", action_input=reply, success=False, error=action_result.error)
                    break
                if i < len(replies) - 1:
                    time.sleep(1.5)

            # 标记所有 to_reply 的消息为已回复（用最后一条回复文本）
            for msg in to_reply:
                self.global_store.mark_replied(chat_name, msg, reply_text)

            # 触发记忆更新（异步，不阻塞）
            if self.memory_engine is not None:
                if is_group:
                    # 群聊：同时更新群 wiki 和最后发言者 wiki
                    self.memory_engine.update_group_wiki(
                        group_name=chat_name,
                        chat_name=chat_name,
                        messages=to_reply,
                        bot_replies=replies,
                    )
                    user_name = to_reply[-1].sender if to_reply else ""
                    if user_name:
                        self.memory_engine.update_user_wiki(
                            user_name=user_name,
                            chat_name=chat_name,
                            messages=to_reply,
                            bot_replies=replies,
                        )
                else:
                    # 私聊：只更新用户 wiki
                    self.memory_engine.update_user_wiki(
                        user_name=chat_name,
                        chat_name=chat_name,
                        messages=to_reply,
                        bot_replies=replies,
                    )
            return

        except Exception as exc:
            self.logger.log_exception(tick_id, phase="tick", exc=exc)
            if self.debug_logger.current:
                self.debug_logger.log_action("none", action_input="", success=False, error=f"异常: {exc}")
            raise
        finally:
            if self.debug_logger.current is not None:
                try:
                    path = self.debug_logger.save()
                    self.logger.debug(f"调试日志已保存: {path}")
                except Exception:
                    pass
                self.debug_logger.current = None
            self.save_sessions()

    def save_sessions(self) -> None:
        """保存全局状态到磁盘（增量保存，只保存有变化的聊天）。"""
        try:
            self.global_store.save()
        except Exception as e:
            self.logger.warning(f"保存全局状态失败: {e}")

    def run_auto(self, interval: float = 5.0) -> None:
        """自动运行主循环"""
        self.running = True
        self._interval = interval
        while self.running:
            try:
                self.tick()
            except Exception as e:
                self.logger.error(f"Tick #{self._tick_id} 未捕获异常: {e}", exc_info=True)
            time.sleep(interval)

    def _try_switch_to_unread_chat(self, result: PerceptionResult) -> str:
        """检测到其他聊天有未读时，切换到未读数最多的那个。

        WeFlow 模式下优先使用 API 轮询检测未读（比 OCR 识别角标更可靠）。
        防抖：10 秒内不重复切换同一个目标，防止反复点击导致右侧折叠。
        """
        if not getattr(self, 'enable_chat_switch', True):
            return ""

        current_chat = _normalize_chat_name(result.chat_name)
        target_name = ""
        target_unread = 0

        # ===== WeFlow 模式：API 轮询检测未读 =====
        if self._weflow_mode in ("weflow", "hybrid"):
            try:
                from src.perception.weflow_pipeline import WeFlowPipeline
                weflow = getattr(self.perception, '_weflow_pipeline', None)
                self.logger.info(f"[WeFlow] 切换检测: weflow={weflow is not None}, initialized={getattr(weflow, '_initialized', False)}")
                if weflow and weflow._initialized:
                    unread_chats = weflow.check_unread_all()
                    self.logger.info(f"[WeFlow] check_unread_all 返回 {len(unread_chats)} 个未读")
                    # 过滤当前聊天和免回复列表
                    for item in unread_chats:
                        name = _normalize_chat_name(item["name"])
                        self.logger.info(f"[WeFlow] 未读候选: {name} ({item['unread_count']}条), current={current_chat}")
                        if name == current_chat:
                            continue
                        if name in {_normalize_chat_name(c) for c in self.no_reply_chats}:
                            continue
                        target_name = item["name"]
                        target_unread = item["unread_count"]
                        break
                    if target_name:
                        self.logger.info(f"[WeFlow] 检测到未读: {target_name} ({target_unread}条)")
            except Exception as e:
                self.logger.warning(f"[WeFlow] 未读检测失败: {e}")

        # ===== OCR fallback：截图识别未读角标 =====
        # WeFlow 模式下：API 已经检测过未读，如果 API 返回空（没有未读），
        # 直接信任 API，不 fallback 到 OCR（OCR 在小窗口中误识别率太高，会导致无限切换）
        if self._weflow_mode in ("weflow", "hybrid") and not target_name:
            return ""

        if not target_name:
            chat_list_items = result.chat_list_items
            if not chat_list_items:
                return ""

            unread_items = [
                item for item in chat_list_items
                if item.unread_count
                and _normalize_chat_name(item.nickname) != current_chat
                and _normalize_chat_name(item.nickname) not in {
                    _normalize_chat_name(c) for c in self.no_reply_chats
                }
            ]
            if not unread_items:
                return ""

            # 优先选择未读数最多的
            unread_items.sort(key=lambda item: int(item.unread_count) if item.unread_count.isdigit() else 0, reverse=True)
            target = unread_items[0]
            target_name = target.nickname
            target_unread = target.unread_count

        if not target_name:
            return ""

        target_norm = _normalize_chat_name(target_name)

        # 防抖：10 秒内不重复切换同一个目标
        now = time.time()
        if target_norm == self._last_switch_target and (now - self._last_switch_time) < self._switch_debounce_seconds:
            self.logger.info(f"[WeFlow] 防抖: {target_name} 最近已切换，跳过")
            return ""

        window_rect = result.window_rect
        scale_factor = result.scale_factor
        if window_rect is None:
            self.logger.info(f"[WeFlow] window_rect 为 None，无法切换")
            return ""

        clicker = ChatListClicker(window_rect, scale_factor)

        # WeFlow 模式：在截图的 chat_list_items 中找匹配的 rect
        target_item = None
        if self._weflow_mode in ("weflow", "hybrid"):
            weflow = getattr(self.perception, '_weflow_pipeline', None)
            for item in result.chat_list_items:
                # 1) 直接昵称匹配
                if _normalize_chat_name(item.nickname) == target_norm:
                    target_item = item
                    self.logger.info(f"[WeFlow] chat_list_items 昵称匹配 '{target_name}'")
                    break
                # 2) talker 匹配（API 返回的是 talker/wxid，OCR 显示的是昵称）
                if weflow:
                    item_talker = weflow._resolve_talker(item.nickname)
                    if item_talker and _normalize_chat_name(item_talker) == target_norm:
                        target_item = item
                        self.logger.info(f"[WeFlow] chat_list_items talker 匹配 '{target_name}' via '{item.nickname}'")
                        break
            if target_item is None:
                self.logger.info(f"[WeFlow] chat_list_items 中无匹配 '{target_name}' 的项，共 {len(result.chat_list_items)} 个")

        # fallback 1: OCR 列表中的第一个未读项
        if target_item is None:
            unread_items = [
                item for item in result.chat_list_items
                if item.unread_count and _normalize_chat_name(item.nickname) != current_chat
                and _normalize_chat_name(item.nickname) not in {_normalize_chat_name(c) for c in self.no_reply_chats}
            ]
            self.logger.info(f"[WeFlow] chat_list_items 未读项: {len(unread_items)}/{len(result.chat_list_items)}")
            if unread_items:
                target_item = unread_items[0]
                target_name = target_item.nickname
                target_unread = target_item.unread_count
            elif result.chat_list_items and self._weflow_mode in ("weflow", "hybrid"):
                # fallback 2: WeFlow 检测到未读但 OCR 列表中无未读标记，尝试点击列表第一项
                #（WeFlow 已知有未读，但 OCR 未识别到角标，可能是小窗口中角标太小）
                target_item = result.chat_list_items[0]
                self.logger.info(f"[WeFlow] 未读 '{target_name}' 无精确 rect，尝试点击列表第一项 '{target_item.nickname}'")

        if target_item is None:
            self.logger.info(f"[WeFlow] 无法找到可点击的列表项，chat_list_items={len(result.chat_list_items)}")
            return ""

        self.logger.info(f"[WeFlow] 准备点击 '{target_item.nickname}' at ({target_item.rect.x},{target_item.rect.y})")
        clicked = clicker.click_item(target_item)
        if clicked:
            self._last_switch_target = target_norm
            self._last_switch_time = now
            self.logger.info(f"🔄 切换聊天: {target_name!r} (未读 {target_unread})")
            self.debug_logger.log_bot_decision(switch_target=target_name, switch_reason=f"未读 {target_unread}")
            return target_name
        self.logger.info(f"[WeFlow] 点击失败: '{target_item.nickname}'")
        return ""

    def send_to_chat(self, chat_name: str, text: str) -> ActionResult:
        """外部系统调用此接口主动发消息到指定聊天。"""
        result = self.sender.send(text)
        if result.success:
            norm = _normalize_chat_name(chat_name)
            is_group = _is_group_chat_name(chat_name)
            # 创建一条虚拟的已回复消息记录，放入 pending 等感知层确认
            from src.models.base import ChatMessage, SenderType
            msg = ChatMessage(
                text=text, sender="bot", sender_type=SenderType.SELF,
                chat_name=norm, replied=True, reply_text=text, reply_time=time.time()
            )
            state = self.global_store.chats.get(norm)
            if state is not None:
                state.pending_self_messages.append(msg)
                self.logger.info("[Pending] %s 记录 pending self 消息 (pending 队列长度=%d): %.60s",
                                     norm, len(state.pending_self_messages), text)
        return result
