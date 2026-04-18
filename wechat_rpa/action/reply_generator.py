#!/usr/bin/env python3
"""
回复生成器

使用 LLM 生成回复内容，包含完整的回复策略
"""

import os
import re
import time
from typing import Optional, List, Dict
from dataclasses import dataclass, field


@dataclass
class MessageContext:
    """消息上下文"""
    chat_name: str
    sender: str
    text: str
    sender_type: str = "other"  # 'self' | 'other'
    is_at_me: bool = False
    is_group: bool = False       # 是否是群聊
    confidence: float = 0.0


@dataclass
class ChatSession:
    """单个聊天会话的状态"""
    chat_id: str = ""
    chat_name: str = ""
    last_message: str = ""
    last_reply: str = ""
    replied_history: Dict[str, float] = field(default_factory=dict)
    message_count: int = 0


class ReplyGenerator:
    """回复生成器 - 完整版（从 V1 迁移）"""
    
    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM 客户端，如果为 None 使用简单回复
        """
        self.llm = llm_client
        
        # 配置（从 V1 迁移）
        self.cooldown_seconds = 30      # 消息冷却期
        self.min_confidence = 0.3       # 最低置信度
        
        # 系统提示词
        self.system_prompt = """你是微信群里的智能助手"熊猫头"，请遵守以下规则：
1. 回复简洁有趣，适合群聊氛围
2. 适当使用 emoji 和熊猫元素 🐼
3. 被@时优先回复
4. 不知道时诚实说不知道
5. 不要刷屏，保持克制"""
        
        # 系统消息过滤模式（从 V1 迁移）
        self.system_patterns = [
            re.compile(r'\[图片\]|\[视频\]|\[语音\]|\[文件\]|\[动画表情\]'),
            re.compile(r'撤回了一条消息|邀请你加入群聊'),
            re.compile(r'^\d{2}:\d{2}$'),  # 时间戳
            re.compile(r'今天|昨天|星期[一二三四五六日]'),
        ]
        
        # 会话管理
        self.sessions: Dict[str, ChatSession] = {}
        self.global_last_reply = ""      # 全局上一条回复
        self.global_last_reply_time = 0  # 全局上一条回复时间
        
        # 我的昵称（用于@检测）
        self.my_nickname = os.getenv("WECHAT_NICKNAME", "")
    
    def get_or_create_session(self, chat_id: str, chat_name: str) -> ChatSession:
        """获取或创建聊天会话"""
        if chat_id not in self.sessions:
            self.sessions[chat_id] = ChatSession(
                chat_id=chat_id,
                chat_name=chat_name
            )
        return self.sessions[chat_id]
    
    def should_reply(self, context: MessageContext, session: ChatSession = None) -> bool:
        """
        判断是否需要回复（完整策略，从 V1 迁移）
        
        Args:
            context: 消息上下文
            session: 聊天会话状态
            
        Returns:
            是否需要回复
        """
        text = context.text
        
        # 1. 基本条件检查
        if not text or len(text.strip()) < 2:
            return False
        
        # 2. 过滤系统消息
        for pattern in self.system_patterns:
            if pattern.search(text):
                return False
        
        # 3. 不回复自己的消息
        if context.sender_type == "self":
            return False
        
        # 4. 置信度检查
        if context.confidence < self.min_confidence:
            return False
        
        # 5. 检查冷却期
        now = time.time()
        
        # 全局冷却
        if now - self.global_last_reply_time < self.cooldown_seconds:
            return False
        
        # 会话内冷却（避免重复回复同一内容）
        if session:
            last_replied = session.replied_history.get(text, 0)
            if now - last_replied < self.cooldown_seconds:
                return False
            
            # 避免重复回复相同内容
            if text == session.last_reply or text in session.last_reply:
                return False
        
        # 6. 私聊直接回复（不需要@）
        if not context.is_group:
            return True
        
        # 7. 群聊中，被@时回复
        if context.is_at_me:
            return True
        
        # 8. 群聊中其他触发条件：
        # - 关键词触发
        # - 随机回复（概率触发）
        # - 特定发件人
        
        return False
    
    def generate(self, context: MessageContext, session: ChatSession = None, 
                 history: List[dict] = None) -> Optional[str]:
        """
        生成回复
        
        Args:
            context: 消息上下文
            session: 聊天会话
            history: 历史消息
            
        Returns:
            回复内容，不需要回复时返回 None
        """
        # 判断是否需要回复
        if not self.should_reply(context, session):
            return None
        
        # 生成回复
        if self.llm:
            reply = self._generate_with_llm(context, history)
        else:
            reply = self._generate_simple(context)
        
        # 更新状态
        if session:
            session.last_reply = reply
            session.replied_history[context.text] = time.time()
            session.message_count += 1
        
        self.global_last_reply = reply
        self.global_last_reply_time = time.time()
        
        return reply
    
    def _generate_with_llm(self, context: MessageContext, history: List[dict] = None) -> str:
        """使用 LLM 生成回复"""
        try:
            # 构建提示
            prompt = f"当前聊天: {context.chat_name}\n"
            prompt += f"发言人: {context.sender}\n"
            if context.is_at_me:
                prompt += "（你被@了）\n"
            prompt += f"消息: {context.text}\n"
            
            # 这里应该调用 LLM
            # 暂时返回简单回复
            return self._generate_simple(context)
            
        except Exception as e:
            print(f"LLM 生成失败: {e}")
            return self._generate_simple(context)
    
    def _generate_simple(self, context: MessageContext) -> str:
        """简单回复（无 LLM 时）"""
        # 根据上下文生成不同回复
        text = context.text.lower()
        
        # @检测回复
        if context.is_at_me:
            at_replies = [
                "收到！🐼",
                "在呢！有什么可以帮你的吗？",
                "👋 来啦来啦~",
                "熊猫头已上线！",
            ]
            import random
            return random.choice(at_replies)
        
        # 默认回复
        default_replies = [
            "收到！🐼",
            "明白了~",
            "👍",
            "哈哈",
            "了解！",
        ]
        import random
        return random.choice(default_replies)
