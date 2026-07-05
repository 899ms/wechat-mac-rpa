#!/usr/bin/env python3
"""ReAct + Self-Refine 单元测试。

仅验证 ReplyGenerator 内部的 ReAct 循环、think 工具注册与执行、
Self-Refine（Feedback + Iterate）开关及 max_tool_calls 降级逻辑，
不调用真实 LLM API。
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from src.models.base import ChatMessage, SenderType
from src.reply.generator import MAX_TOOL_CALLS, ReplyGenerator


@dataclass
class MockFunction:
    name: str
    arguments: str


@dataclass
class MockToolCall:
    id: str
    type: str
    function: MockFunction

    def __init__(self, name: str, arguments: str, id: str = "tc_1", type: str = "function"):
        self.id = id
        self.type = type
        self.function = MockFunction(name=name, arguments=arguments)


@dataclass
class MockResponse:
    content: str = ""
    tool_calls: List[MockToolCall] = field(default_factory=list)
    reasoning_content: str = ""


class MockLLM:
    """按顺序返回预设响应的 Mock LLM。

    支持两种用法：
    1. 传入 `responses` 列表，每次 chat() 按顺序弹出；
    2. 传入 `response_func(messages, tools, **kwargs)`，在列表耗尽后动态生成响应。
    """

    def __init__(
        self,
        responses: Optional[List[Any]] = None,
        response_func: Optional[Any] = None,
    ):
        self.responses = list(responses) if responses else []
        self.response_func = response_func
        self.calls: List[Dict[str, Any]] = []
        self.index = 0

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})

        if self.index < len(self.responses):
            resp = self.responses[self.index]
            self.index += 1
        elif self.response_func is not None:
            resp = self.response_func(messages, tools=tools, **kwargs)
        else:
            resp = '{"replies": ["fallback"]}'

        if isinstance(resp, str):
            return MockResponse(content=resp)
        return resp


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def sample_message():
    return ChatMessage(
        text="在吗",
        sender="Alice",
        sender_type=SenderType.OTHER,
        chat_name="Alice",
    )


def _make_generator(mock_llm_instance, enable_self_refine: bool = True) -> ReplyGenerator:
    """构造已关闭环境变量影响的 ReplyGenerator。"""
    gen = ReplyGenerator(llm_client=mock_llm_instance)
    gen.enable_self_refine = enable_self_refine
    gen.enable_react_tools = True
    return gen


class TestThinkTool:
    def test_think_tool_registered(self):
        gen = ReplyGenerator(llm_client=MockLLM())
        assert gen.tool_registry.has("think")

    def test_think_tool_returns_confirmation(self):
        gen = ReplyGenerator(llm_client=MockLLM())
        tool = gen.tool_registry.get("think")
        result = tool.execute('{"thought": "test"}')
        assert "思考已记录" in result


class TestSelfRefine:
    def test_self_refine_pass_skips_iterate(self, mock_llm, sample_message):
        mock_llm.responses = [
            '{"skills": []}',                       # skill router
            '{"replies": ["test reply"]}',          # ReAct 生成
            '{"decision": "pass"}',                 # Feedback
        ]
        gen = _make_generator(mock_llm, enable_self_refine=True)
        replies = gen.generate([sample_message], [sample_message])

        assert replies == ["test reply"]
        assert gen.last_self_refine_applied is True
        assert gen.last_feedback_decision == "pass"
        assert gen.last_iterate_count == 0

    def test_self_refine_fail_triggers_iterate(self, mock_llm, sample_message):
        mock_llm.responses = [
            '{"skills": []}',                       # skill router
            '{"replies": ["bad reply"]}',           # ReAct 生成
            '{"decision": "fail", "issues": ["太正式"]}',  # Feedback
            '{"replies": ["好的吧"]}',              # Iterate
        ]
        gen = _make_generator(mock_llm, enable_self_refine=True)
        replies = gen.generate([sample_message], [sample_message])

        assert replies == ["好的吧"]
        assert gen.last_self_refine_applied is True
        assert gen.last_feedback_decision == "fail"
        assert gen.last_iterate_count == 1

    def test_self_refine_disabled(self, mock_llm, sample_message):
        mock_llm.responses = [
            '{"skills": []}',                       # skill router
            '{"replies": ["reply"]}',               # 单次推理
        ]
        gen = _make_generator(mock_llm, enable_self_refine=False)
        replies = gen.generate([sample_message], [sample_message])

        assert replies == ["reply"]
        assert gen.last_self_refine_applied is False
        assert gen.last_feedback_decision == ""
        assert gen.last_iterate_count == 0
        # 关闭 Self-Refine 后不应调用 Feedback/Iterate，只应有 2 次 LLM 调用
        assert len(mock_llm.calls) == 2


class TestReActLoop:
    def test_max_tool_calls_limit(self, sample_message):
        """达到 MAX_TOOL_CALLS 后应强制禁用 tools 并返回 JSON，避免无限循环。"""
        call_count = 0

        def _response_func(messages, tools=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # skill router
                return MockResponse(content='{"skills": []}')
            if tools:
                # 持续返回 think 工具调用，迫使进入下一轮 ReAct
                return MockResponse(
                    tool_calls=[
                        MockToolCall(
                            name="think",
                            arguments='{"thought": "thinking"}',
                            id=f"tc_{call_count}",
                        )
                    ]
                )
            # tools 被强制禁用后，必须输出最终 JSON
            return MockResponse(content='{"replies": ["forced final"]}')

        mock_llm = MockLLM(response_func=_response_func)
        gen = _make_generator(mock_llm, enable_self_refine=False)
        replies = gen.generate([sample_message], [sample_message])

        assert replies == ["forced final"]

        # 调用次数应为：1 次 skill router + MAX_TOOL_CALLS 次 tool 调用 + 1 次强制 JSON
        assert call_count == 1 + MAX_TOOL_CALLS + 1

        # 验证确实存在 think 工具调用记录
        assert any(tc["tool_name"] == "think" for tc in gen.last_tool_calls)
