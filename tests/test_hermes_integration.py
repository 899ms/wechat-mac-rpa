#!/usr/bin/env python3
"""
Bot ↔ Hermes 联调测试脚本
验证：
1. Hermes client 能正确创建并连接
2. ReplyGenerator 的 active_llm 切换逻辑正确
3. use_hermes 触发时，tool 结果上下文保留到 Hermes
4. 端到端生成流程通畅
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from unittest.mock import MagicMock, patch

# 提前导入并定义常量
from src.models.base import SenderType
USER_TYPE = SenderType.OTHER  # SenderType 没有 USER，用 OTHER 表示普通用户


def test_hermes_client_connection():
    """测试 1: Hermes client 能连接并返回响应"""
    print("\n[测试 1] Hermes client 连接...")
    from src.llm.openclaw_client import OpenClawClient

    client = OpenClawClient(
        base_url="http://127.0.0.1:8642",
        model="hermes-agent",
        max_tokens=2000,
    )
    resp = client.chat(
        messages=[{"role": "user", "content": "你好，请回复 JSON 格式 {\"replies\": [\"你好\"]}"}],
        max_tokens=100,
    )
    assert isinstance(resp, str), f"期望 str，得到 {type(resp)}"
    assert len(resp) > 0, "Hermes 返回空字符串"
    print(f"  ✅ Hermes 响应: {resp[:100]}")
    return True


def test_generator_active_llm_switch():
    """测试 2: matched_skills 时 active_llm 正确切换"""
    print("\n[测试 2] active_llm 切换逻辑...")
    from src.reply.generator import ReplyGenerator
    from src.models.base import ChatMessage

    # Mock 两个 LLM
    mock_deepseek = MagicMock()
    mock_deepseek.chat.return_value = '{"replies": ["deepseek 回复"]}'

    mock_hermes = MagicMock()
    mock_hermes.chat.return_value = '{"replies": ["hermes 回复"]}'

    gen = ReplyGenerator(llm_client=mock_deepseek, complex_llm_client=mock_hermes)

    # Mock skill 路由返回一个 skill
    with patch.object(gen, '_route_skills', return_value=['test_skill']):
        with patch.object(gen, '_load_skill_content', return_value='test skill content'):
            with patch.object(gen, '_load_skill_one_liners', return_value=''):
                msg = ChatMessage(
                    chat_name="测试群",
                    sender="用户A",
                    sender_type=USER_TYPE,
                    text="测试消息",
                    timestamp=datetime.now(),
                )
                replies = gen.generate([msg], [msg])

    # 验证调用了 hermes（因为 matched_skills）
    assert mock_hermes.chat.called, "matched_skills 时应该调用 hermes"
    assert not mock_deepseek.chat.called, "matched_skills 时不应该调用 deepseek"
    assert replies == ["hermes 回复"], f"期望 ['hermes 回复']，得到 {replies}"
    print(f"  ✅ matched_skills 时正确切到 Hermes")
    return True


def test_use_hermes_fallback():
    """测试 3: deepseek 返回 use_hermes 时，切 Hermes 并保留 tool 结果"""
    print("\n[测试 3] use_hermes fallback 逻辑...")
    from src.reply.generator import ReplyGenerator
    from src.models.base import ChatMessage, SenderType

    mock_deepseek = MagicMock()
    # 第一轮：deepseek 返回 use_hermes
    mock_deepseek.chat.return_value = '{"use_hermes": true}'

    mock_hermes = MagicMock()
    mock_hermes.chat.return_value = '{"replies": ["hermes 复杂回复"]}'

    gen = ReplyGenerator(llm_client=mock_deepseek, complex_llm_client=mock_hermes)

    with patch.object(gen, '_route_skills', return_value=[]):
        with patch.object(gen, '_load_skill_one_liners', return_value=''):
            msg = ChatMessage(
                chat_name="测试群",
                sender="用户A",
                sender_type=USER_TYPE,
                text="分析下阿里巴巴股票",
                timestamp=datetime.now(),
            )
            replies = gen.generate([msg], [msg])

    # 验证 deepseek 被调用了
    assert mock_deepseek.chat.called, "应该先调用 deepseek"
    # 验证 hermes 被调用了
    assert mock_hermes.chat.called, "deepseek 返回 use_hermes 后应该调用 hermes"

    # 验证传给 hermes 的 messages 包含 system + user（保留上下文）
    hermes_call_args = mock_hermes.chat.call_args
    hermes_messages = hermes_call_args.kwargs.get("messages") or hermes_call_args[1].get("messages")
    assert hermes_messages is not None, "hermes 调用应该有 messages 参数"
    assert hermes_messages[0]["role"] == "system", "第一条应该是 system"
    assert "幽默" in hermes_messages[0]["content"] or "风格" in hermes_messages[0]["content"], \
        f"system prompt 应该是 hermes 风格，实际: {hermes_messages[0]['content'][:50]}"

    assert replies == ["hermes 复杂回复"], f"期望 ['hermes 复杂回复']，得到 {replies}"
    print(f"  ✅ use_hermes fallback 正确，切到 Hermes 并保留上下文")
    return True


def test_run_bot_creates_clients():
    """测试 4: run_bot.py 能正确创建双 client"""
    print("\n[测试 4] run_bot.py 双 client 创建...")
    from run_bot import _create_llm_client, _create_hermes_client

    llm = _create_llm_client()
    assert llm is not None, "LLM client 创建失败"
    print(f"  ✅ LLM client: {type(llm).__name__}")

    hermes = _create_hermes_client()
    assert hermes is not None, "Hermes client 创建失败（请确认 Hermes 已启动在 8642 端口）"
    print(f"  ✅ Hermes client: {type(hermes).__name__}")

    # 验证 Hermes 能直接调用
    resp = hermes.chat(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
    )
    assert isinstance(resp, str) and len(resp) > 0, "Hermes 直接调用失败"
    print(f"  ✅ Hermes 直接调用响应: {resp[:60]}")
    return True


def test_end_to_end_with_mock_tools():
    """测试 5: 端到端 - deepseek 调 tool → use_hermes → Hermes 生成"""
    print("\n[测试 5] 端到端 tool → use_hermes → Hermes...")
    from src.reply.generator import ReplyGenerator
    from src.models.base import ChatMessage, SenderType

    # 模拟 deepseek 返回 tool_calls（stock_query）
    mock_deepseek = MagicMock()
    tool_call_msg = MagicMock()
    tool_call_msg.content = ''
    tool_call_msg.tool_calls = [MagicMock(
        id='call_1',
        type='function',
        function=MagicMock(name='stock_query', arguments='{"stock_code": "BABA"}')
    )]
    # 第二轮返回 use_hermes
    mock_deepseek.chat.side_effect = [
        tool_call_msg,
        '{"use_hermes": true}',
    ]

    mock_hermes = MagicMock()
    mock_hermes.chat.return_value = '{"replies": ["阿里涨了 3%，市场信心回暖"]}'

    gen = ReplyGenerator(llm_client=mock_deepseek, complex_llm_client=mock_hermes)

    # Mock stock_query 工具返回结果
    def mock_stock_query(stock_code=""):
        return "阿里巴巴(BABA): 股价 85.32, 涨幅 +3.15%, 成交量 1200万"
    gen.tool_registry.register(
        name="stock_query",
        description="查询股票",
        parameters={"type": "object", "properties": {"stock_code": {"type": "string"}}},
        func=mock_stock_query,
    )

    with patch.object(gen, '_route_skills', return_value=[]):
        with patch.object(gen, '_load_skill_one_liners', return_value=''):
            msg = ChatMessage(
                chat_name="测试群",
                sender="用户A",
                sender_type=USER_TYPE,
                text="阿里巴巴股票怎么样",
                timestamp=datetime.now(),
            )
            replies = gen.generate([msg], [msg])

    assert replies == ["阿里涨了 3%，市场信心回暖"], f"端到端结果错误: {replies}"
    # 验证 hermes 收到的 messages 包含 tool 结果
    hermes_call_args = mock_hermes.chat.call_args
    hermes_messages = hermes_call_args.kwargs.get("messages") or hermes_call_args[1].get("messages")
    msgs_json = str(hermes_messages)
    assert "tool" in msgs_json or "阿里巴巴" in msgs_json, \
        f"Hermes messages 应该包含 tool 结果上下文，实际: {msgs_json[:200]}"
    print(f"  ✅ 端到端通畅：deepseek 调 tool → use_hermes → Hermes 生成")
    return True


def main():
    print("=" * 60)
    print("🧪 Bot ↔ Hermes 联调测试")
    print("=" * 60)

    results = []
    tests = [
        ("Hermes 连接", test_hermes_client_connection),
        ("active_llm 切换", test_generator_active_llm_switch),
        ("use_hermes fallback", test_use_hermes_fallback),
        ("run_bot 双 client", test_run_bot_creates_clients),
        ("端到端 tool→Hermes", test_end_to_end_with_mock_tools),
    ]

    for name, test_fn in tests:
        try:
            test_fn()
            results.append((name, True, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  ❌ {name} 失败: {e}")

    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, err in results:
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status} {name}")
        if err:
            print(f"       错误: {err}")
    print(f"\n总计: {passed}/{len(results)} 通过")

    if passed == len(results):
        print("🎉 所有测试通过！Bot ↔ Hermes 联调完成。")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查配置和日志。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
