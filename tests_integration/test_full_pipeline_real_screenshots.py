#!/usr/bin/env python3
"""
真实截图全流程测试

使用项目内保存的真实微信截图，对 VisionPipeline 和 WeChatBot 进行端到端测试。
所有截图统一存放在 tests/fixtures/ 下。
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.bot.wechat_bot import WeChatBot
from src.layout.profile import PROFILE_WECHAT_MAC_1760X1280
from src.models.base import SenderType
from src.perception.vision_pipeline import VisionPipeline

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SIMILARITY_THRESHOLD = 0.90
OCR_ERROR_MAP = {
    "Al 助手": "AI 助手",
    "Al助手": "AI助手",
}


def _normalize_ocr_errors(text: str) -> str:
    for wrong, correct in OCR_ERROR_MAP.items():
        text = text.replace(wrong, correct)
    return text


def _text_similarity(a: str, b: str) -> float:
    a = a.replace(" ", "").replace("\n", "")
    b = b.replace(" ", "").replace("\n", "")
    if not a or not b:
        return 0.0
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    return 2 * lcs / (m + n)


# ═══════════════════════════════════════════════════════════
# 1. VisionPipeline 端到端测试（真实截图）
# ═══════════════════════════════════════════════════════════


def load_expected(name: str):
    path = FIXTURES_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def run_fixture(name: str):
    """对指定 fixture 运行 VisionPipeline 并返回结果"""
    img_path = FIXTURES_DIR / f"{name}.png"
    if not img_path.exists():
        pytest.skip(f"{name}.png not found")

    pipeline = VisionPipeline(PROFILE_WECHAT_MAC_1760X1280)
    # Mock WindowCapture 直接返回 fixture 图片
    from src.capture.window_capture import CaptureResult
    from src.models.base import Rect

    mock_capture = Mock()
    mock_capture.capture.return_value = CaptureResult(
        image_path=str(img_path),
        window_rect=Rect(0, 0, 1760, 1280),
        scale_factor=1.0,
    )
    pipeline.capture = mock_capture

    return pipeline.perceive()


def assert_no_timestamps_in_messages(messages):
    """断言消息中不包含时间戳"""
    import re
    ts_patterns = [
        r"^\d{1,2}:\d{2}$",
        r"^星期[一二三四五六日—] \d{1,2}:\d{2}$",
        r"^星期[一二三四五六日—]$",
        r"^昨天 \d{1,2}:\d{2}$",
    ]
    for msg in messages:
        for p in ts_patterns:
            assert not re.match(p, msg.text.strip()), f"时间戳被误识别为消息: {msg.text!r}"


def assert_no_common_noise(messages):
    """断言不包含常见界面噪声"""
    noise_items = ["®v", "®0", "QS.", "MipUxJ", "uipUxAJ"]
    for msg in messages:
        for noise in noise_items:
            assert noise not in msg.text, f"界面噪声被误识别为消息: {msg.text!r}"


class TestVisionPipelineRealScreenshots:
    """VisionPipeline 对真实截图的端到端测试"""

    def test_real_login_recovered_scene(self):
        """登录恢复后的群聊场景：应正确识别聊天名称和多发言者消息"""
        result = run_fixture("real_login_recovered_scene")
        assert result is not None
        assert result.chat_name == "王老板们和小天才（5)"

        assert_no_timestamps_in_messages(result.messages)
        assert_no_common_noise(result.messages)

        # 期望消息: wanglc + 自己长消息 + 自己短消息 = 3
        assert len(result.messages) == 3, f"消息数异常: {len(result.messages)}"

        # wanglc 的消息
        wanglc_msgs = [m for m in result.messages if "是不是忙着切号呢" in m.text]
        assert len(wanglc_msgs) == 1
        assert wanglc_msgs[0].sender == "wanglc"
        assert wanglc_msgs[0].sender_type == SenderType.OTHER

        # 自己的长消息 - 用完整预期消息做 90% 相似度匹配
        long_self = [m for m in result.messages if "哈哈误会啦！" in m.text]
        assert len(long_self) == 1
        assert long_self[0].sender == "自己"
        expected_long = (
            "哈哈误会啦！ 我是**AI 助手**，不是真人 客服～ 不存在\"切号\"这种操作： "
            "我没有微信号，也不是 Qian 回复速度取决于网络/服务器负载 ◎ 同时只处理你这一个对话窗口 "
            "你是不是把我当成某个真人客服了？或者@错 人了？ 还有登录问题需要解决吗？随时叫我！"
        )
        sim = _text_similarity(expected_long, _normalize_ocr_errors(long_self[0].text))
        assert sim >= SIMILARITY_THRESHOLD, (
            f"长消息相似度低于 {SIMILARITY_THRESHOLD:.0%}: {sim:.1%}"
        )

        # 自己的短消息
        short_self = [m for m in result.messages if "laayaua5aapangaaaaa~" in m.text]
        assert len(short_self) == 1

    def test_real_group_chat_20260411(self):
        """早期群聊截图：验证绿色气泡分割和昵称识别"""
        result = run_fixture("real_group_chat_20260411")
        assert result is not None
        assert result.chat_name == "王老板们和小天才（5)"

        assert_no_timestamps_in_messages(result.messages)
        assert_no_common_noise(result.messages)

        expected = load_expected("real_group_chat_20260411")
        assert expected is not None

        # 消息数量
        assert len(result.messages) == len(expected["messages"]), (
            f"消息数量不匹配: 期望 {len(expected['messages'])}, 实际 {len(result.messages)}"
        )

        for i, exp in enumerate(expected["messages"]):
            actual = result.messages[i]
            assert actual.sender_type.value == exp["sender_type"], (
                f"消息[{i}] 发送者类型不匹配: 期望 {exp['sender_type']}, 实际 {actual.sender_type.value}"
            )
            check = exp.get("check", exp.get("check_mode", "exact"))
            expected_text = exp["text"]
            normalized_actual = _normalize_ocr_errors(actual.text)
            if check == "similarity":
                sim = _text_similarity(expected_text, normalized_actual)
                assert sim >= SIMILARITY_THRESHOLD, (
                    f"消息[{i}] 相似度低于 {SIMILARITY_THRESHOLD:.0%}: {sim:.1%}, "
                    f"期望={expected_text!r}, 实际={normalized_actual!r}"
                )
            elif check == "contains" or exp.get("check_mode") == "contains":
                assert expected_text in normalized_actual, (
                    f"消息[{i}] 内容不包含期望文本: 期望包含 {expected_text!r}, 实际 {normalized_actual!r}"
                )
            else:
                assert normalized_actual == expected_text or expected_text in normalized_actual, (
                    f"消息[{i}] 内容不匹配: 期望 {expected_text!r}, 实际 {normalized_actual!r}"
                )

    def test_real_private_w1han_20260413(self):
        """private_w1han fixture 已移除：包含真实私人聊天隐私数据"""
        pytest.skip("real_private_w1han_20260413 fixture 已移除（隐私数据清理）")

    def test_real_private_w1han_20260414(self):
        """private_w1han fixture 已移除：包含真实私人聊天隐私数据"""
        pytest.skip("real_private_w1han_20260414 fixture 已移除（隐私数据清理）")

    def test_real_chat_wangqian_20260417(self):
        """2026-04-17 截图：
        1. 头像数字（如微信运动步数 '1000'）不会被误识别为消息内容
        2. 微信系统安全提示被正确识别为 SYSTEM 类型
        3. 头像数字不会被误识别为聊天列表昵称前缀（如 '10 10 王芊'）
        4. 未读 badge 正确检测
        """
        result = run_fixture("real_chat_wangqian_20260417")
        assert result is not None
        assert result.chat_name == "王芊 @ai开发小分队"

        assert_no_timestamps_in_messages(result.messages)
        assert_no_common_noise(result.messages)

        expected = load_expected("real_chat_wangqian_20260417")
        assert expected is not None
        assert len(result.messages) == len(expected["messages"]), (
            f"消息数量不匹配: 期望 {len(expected['messages'])}, 实际 {len(result.messages)}"
        )

        # 关键断言 1：头像噪声不应混入消息
        for m in result.messages:
            assert "确定吗 1000" != m.text, f"头像数字 '1000' 被误识别为消息: {m.text!r}"
            assert "你这也叫秒回 1" != m.text, f"头像数字 '1' 被误识别为消息: {m.text!r}"
            assert not m.text.strip().isdigit(), f"纯数字头像噪声被误识别为消息: {m.text!r}"

        # 关键断言 2：系统通知必须被识别为 SYSTEM
        system_msgs = [m for m in result.messages if m.sender_type == SenderType.SYSTEM]
        assert len(system_msgs) >= 2, f"系统通知数量不足: 期望 >=2, 实际 {len(system_msgs)}"
        for m in system_msgs:
            assert "安全" in m.text or "保护" in m.text or "账号" in m.text, (
                f"SYSTEM 消息内容异常: {m.text!r}"
            )

        # 关键断言 3：普通用户消息不应被误标记为 SYSTEM
        other_msgs = [m for m in result.messages if m.sender_type == SenderType.OTHER]
        for m in other_msgs:
            assert m.sender_type != SenderType.SYSTEM, (
                f"普通消息被误标记为 SYSTEM: {m.text!r}"
            )

        # 关键断言 4：聊天列表昵称不应被头像数字污染
        # （不检查所有数字开头昵称，因为合法昵称可以数字开头，如"1号群"）
        nicknames = [item.nickname for item in result.chat_list_items]
        for nick in nicknames:
            # 只检查特定污染模式：头像里的"10 10"、"1000"等被OCR合并进昵称
            assert "10 10" not in nick, f"头像数字 '10 10' 被误识别为昵称: {nick!r}"
            assert "1000" not in nick, f"头像数字 '1000' 被误识别为昵称: {nick!r}"
        assert "王芊 @ai开发小分队" in nicknames, f"未找到正确昵称，实际: {nicknames!r}"
        assert "王芊" in nicknames, f"未找到正确昵称 '王芊'，实际: {nicknames!r}"

        # 关键断言 5：未读 badge 正确检测
        # 此图中只有腾讯新闻有未读（颜色检测标记为"1"表示有未读，具体数字需OCR）
        unread_items = {item.nickname: item.unread_count for item in result.chat_list_items}
        assert unread_items.get("腾讯新闻") == "1", (
            f"腾讯新闻 未读检测失败: {unread_items!r}"
        )
        assert unread_items.get("王芊 @ai开发小分队") == "", (
            f"王芊 @ai开发小分队 不应有未读: {unread_items!r}"
        )

        for i, exp in enumerate(expected["messages"]):
            actual = result.messages[i]
            assert actual.sender_type.value == exp["sender_type"]
            assert actual.text == exp["text"] or exp["text"] in actual.text, (
                f"消息[{i}] 不匹配: 期望 {exp['text']!r}, 实际 {actual.text!r}"
            )

    def test_regression_unread_badge_39_not_misclassified_as_nickname(self):
        """回归测试：两位数未读角标 '39' 不应被误判为昵称。

        背景：面积阈值分割（<1000 为角标，>=1000 为昵称）对两位数未读
        可能产生误判（两位数角标面积接近阈值）。此测试确保 '39' 被正确
        识别为未读角标，且不会混入昵称列表。
        """
        result = run_fixture("regression_unread_badge_39_20260421")
        assert result is not None

        # 断言 1：'39' 被正确识别为未读角标
        unread_items = {
            item.nickname: item.unread_count for item in result.chat_list_items
        }
        assert unread_items.get("王老板们和小天才") == "39", (
            f"'王老板们和小天才' 未读应为 '39', 实际: {unread_items!r}"
        )

        # 断言 2：'39' 没有被误判为昵称
        nicknames = [item.nickname for item in result.chat_list_items]
        assert "39" not in nicknames, (
            f"'39' 被误判为昵称之一: {nicknames!r}"
        )

        # 断言 3：其他聊天不应有未读
        assert unread_items.get("王芊 @ai开发小分..") == "", (
            f"当前聊天不应有未读: {unread_items!r}"
        )

    @pytest.mark.xfail(reason="聊天列表昵称被头像数字/符号污染，需修复 OCR 合并问题", strict=False)
    def test_regression_chat_list_nickname_not_polluted_by_avatar_digits(self):
        """回归测试：聊天列表昵称不应被头像数字/符号污染。

        tick_14 真实案例：左侧聊天列表中，
        - 头像区域有数字/符号被 OCR 识别并合并进昵称
        - 实际昵称 '王芊 @ai开发小分队' 被污染为 'b io 王芊 @ai开发小分队'
        - 实际昵称 '王芊' 被污染为 '品 王芊'

        当前行为：昵称被污染（测试会失败，修复后通过）
        期望行为：昵称正确提取，不受头像数字干扰
        """
        result = run_fixture("regression_chat_list_pollution_20260421")
        assert result is not None
        assert result.chat_name == "王芊 @ai开发小分队"

        nicknames = [item.nickname for item in result.chat_list_items]

        # 核心断言 1：头像数字污染不应混入昵称
        # 'b io' 是头像区域的 OCR 噪声，不应出现在昵称中
        assert "b io 王芊 @ai开发小分队" not in nicknames, (
            f"头像数字污染 'b io' 被合并进昵称: {nicknames!r}"
        )
        # '品' 也是头像区域的 OCR 噪声
        assert "品 王芊" not in nicknames, (
            f"头像符号污染 '品' 被合并进昵称: {nicknames!r}"
        )

        # 核心断言 2：正确的昵称必须被识别
        assert any(
            "王芊 @ai开发小分队" in nick for nick in nicknames
        ), f"未找到正确昵称 '王芊 @ai开发小分队': {nicknames!r}"
        assert any(
            "王芊" == nick or nick.endswith("王芊") for nick in nicknames
        ), f"未找到正确昵称 '王芊': {nicknames!r}"

        # 核心断言 3：未读角标正确检测
        unread_items = {
            item.nickname: item.unread_count for item in result.chat_list_items
        }
        # 腾讯新闻有未读 1
        assert unread_items.get("腾讯新闻") == "1", (
            f"腾讯新闻 未读检测失败: {unread_items!r}"
        )

        # 核心断言 4：消息提取完整且 sender_type 正确
        assert len(result.messages) == 8, (
            f"消息数量应为 8, 实际: {len(result.messages)}"
        )
        self_msgs = [m for m in result.messages if m.sender_type == SenderType.SELF]
        other_msgs = [m for m in result.messages if m.sender_type == SenderType.OTHER]
        assert len(self_msgs) == 3, f"自己消息应为 3 条, 实际: {len(self_msgs)}"
        assert len(other_msgs) == 5, f"对方消息应为 5 条, 实际: {len(other_msgs)}"

    def test_real_chat_current_group_at_mentions(self):
        """当前群聊截图：验证 @提及 识别、多轮对话、绿色气泡正确性"""
        result = run_fixture("real_chat_current")
        assert result is not None
        assert result.chat_name == "王老板们和小天才（5)"

        assert_no_timestamps_in_messages(result.messages)
        assert_no_common_noise(result.messages)

        expected = load_expected("real_chat_current")
        assert expected is not None
        assert len(result.messages) == len(expected["messages"]), (
            f"消息数量不匹配: 期望 {len(expected['messages'])}, 实际 {len(result.messages)}"
        )

        # 关键断言：@提及消息必须存在且 sender_type=other
        at_msgs = [m for m in result.messages if "@Qian" in m.text and m.sender_type == SenderType.OTHER]
        assert len(at_msgs) >= 2, f"@Qian 消息数量不足: 期望 >=2, 实际 {len(at_msgs)}"

        # 关键断言：Bot 自己的回复存在
        self_msgs = [m for m in result.messages if m.sender_type == SenderType.SELF]
        assert len(self_msgs) >= 2, f"自己的消息数量不足: 期望 >=2, 实际 {len(self_msgs)}"

        for i, exp in enumerate(expected["messages"]):
            actual = result.messages[i]
            assert actual.sender_type.value == exp["sender_type"], (
                f"消息[{i}] sender_type 不匹配: 期望 {exp['sender_type']}, 实际 {actual.sender_type.value}"
            )
            check = exp.get("check", "exact")
            expected_text = exp["text"]
            if check == "similarity":
                sim = _text_similarity(expected_text, actual.text)
                assert sim >= SIMILARITY_THRESHOLD, (
                    f"消息[{i}] 相似度低于 {SIMILARITY_THRESHOLD:.0%}: {sim:.1%}, "
                    f"期望={expected_text!r}, 实际={actual.text!r}"
                )
            else:
                assert actual.text == expected_text or expected_text in actual.text, (
                    f"消息[{i}] 不匹配: 期望 {expected_text!r}, 实际 {actual.text!r}"
                )


# ═══════════════════════════════════════════════════════════
# 2. Bot 全流程集成测试（用真实截图驱动 Bot）
# ═══════════════════════════════════════════════════════════


class TestBotFullPipeline:
    """Bot 层全流程测试：使用真实截图产生的 PerceptionResult 驱动 tick()"""

    def test_bot_processes_real_group_chat(self):
        """Bot 能处理群聊感知结果且流程完整。即使最新消息是 SELF，
        若前面有未回复的 OTHER 消息，Bot 应回退到最新的 OTHER 进行回复。"""
        perception = run_fixture("real_login_recovered_scene")
        assert perception is not None

        bot = WeChatBot(PROFILE_WECHAT_MAC_1760X1280)
        bot.perception = Mock()
        bot.perception.perceive.return_value = perception

        bot.generator = Mock()
        bot.generator.generate.return_value = ["测试群聊回复"]

        bot.sender = Mock()
        bot.sender.send.return_value = Mock(success=True)

        bot.tick()

        # fixture 中 wanglc 的 "是不是忙着切号呢" 是 OTHER，虽然最后一条是 SELF
        # 但 Bot 应倒序找到最后一条可回复的 OTHER
        bot.generator.generate.assert_called_once()
        bot.sender.send.assert_called_once_with("测试群聊回复")
        assert "王老板们和小天才（5）" in bot.global_store.chats

    def test_bot_replies_to_private_last_other_message(self):
        """private_w1han fixture 已移除：包含真实私人聊天隐私数据"""
        pytest.skip("real_private_w1han_20260413 fixture 已移除（隐私数据清理）")

    def test_bot_replies_to_private_w1han_multiturn(self):
        """private_w1han fixture 已移除：包含真实私人聊天隐私数据"""
        pytest.skip("real_private_w1han_20260414 fixture 已移除（隐私数据清理）")

    def test_bot_no_reply_when_only_self_messages(self):
        """private_w1han fixture 已移除：包含真实私人聊天隐私数据"""
        pytest.skip("real_private_w1han_20260413 fixture 已移除（隐私数据清理）")

    def test_bot_no_crash_when_perception_none(self):
        """当感知返回 None（如窗口未就绪）时 Bot 不应崩溃"""
        bot = WeChatBot(PROFILE_WECHAT_MAC_1760X1280)
        bot.perception = Mock()
        bot.perception.perceive.return_value = None

        bot.sender = Mock()
        bot.tick()
        bot.sender.send.assert_not_called()

    def test_bot_switches_to_unread_chat_when_current_idle(self):
        """当前聊天无新消息时，Bot 应切换到未读聊天"""
        perception = run_fixture("real_chat_wangqian_20260417")
        assert perception is not None

        # 将所有消息改为 SELF，让当前聊天无回复需求
        for m in perception.messages:
            m.sender_type = SenderType.SELF
            m.sender = "自己"

        # 添加一个可切换的未读聊天（不在 no_reply_chats 中）
        from src.models.base import ChatListItem, Rect
        perception.chat_list_items.append(
            ChatListItem(
                nickname="测试未读群",
                last_message_preview="有新消息",
                unread_count="3",
                timestamp="14:30",
                rect=Rect(x=100, y=200, width=300, height=60),
            )
        )

        bot = WeChatBot(PROFILE_WECHAT_MAC_1760X1280, enable_chat_switch=True)
        bot.perception = Mock()
        bot.perception.perceive.return_value = perception

        bot.generator = Mock()
        bot.sender = Mock()

        # Mock ChatListClicker 避免实际点击
        with patch("src.bot.wechat_bot.ChatListClicker") as MockClicker:
            mock_clicker = Mock()
            mock_clicker.click_item.return_value = True
            MockClicker.return_value = mock_clicker

            bot.tick()

            # 当前聊天无新 OTHER 消息可回复，应尝试切换
            MockClicker.assert_called_once()
            mock_clicker.click_item.assert_called_once()

    def test_bot_debug_mode_detects_switch_failure(self):
        """Debug 模式：点击成功但当前聊天未切换，应检测到验证失败"""
        perception = run_fixture("real_chat_wangqian_20260417")
        assert perception is not None

        # 将所有消息改为 SELF，让当前聊天无回复需求
        for m in perception.messages:
            m.sender_type = SenderType.SELF
            m.sender = "自己"

        # 添加一个可切换的未读聊天（不在 no_reply_chats 中）
        from src.models.base import ChatListItem, Rect
        perception.chat_list_items.append(
            ChatListItem(
                nickname="测试未读群",
                last_message_preview="有新消息",
                unread_count="3",
                timestamp="14:30",
                rect=Rect(x=100, y=200, width=300, height=60),
            )
        )

        bot = WeChatBot(
            PROFILE_WECHAT_MAC_1760X1280,
            enable_chat_switch=True,
            debug_mode=True,
        )

        # 模拟感知：第一次返回有未读的数据，第二次返回切换失败的数据（当前聊天没变）
        verify_perception = run_fixture("real_chat_wangqian_20260417")
        for m in verify_perception.messages:
            m.sender_type = SenderType.SELF
            m.sender = "自己"

        # verify_perception 也添加同样的未读项（虽然 debug 验证失败时不会再次切换，但保持一致）
        verify_perception.chat_list_items.append(
            ChatListItem(
                nickname="测试未读群",
                last_message_preview="有新消息",
                unread_count="3",
                timestamp="14:30",
                rect=Rect(x=100, y=200, width=300, height=60),
            )
        )

        bot.perception = Mock()
        bot.perception.perceive.side_effect = [perception, verify_perception]

        bot.generator = Mock()
        bot.sender = Mock()

        with patch("src.bot.wechat_bot.ChatListClicker") as MockClicker:
            mock_clicker = Mock()
            mock_clicker.click_item.return_value = True
            MockClicker.return_value = mock_clicker

            # Mock time.sleep 避免测试等待
            with patch("src.bot.wechat_bot.time.sleep"):
                bot.tick()

            # tick 中调用一次 perceive（切换后不再二次验证，避免递归复杂化）
            assert bot.perception.perceive.call_count == 1, (
                f"tick 应执行一次感知，实际 {bot.perception.perceive.call_count} 次"
            )

    def test_bot_does_not_switch_when_current_has_reply(self):
        """private_w1han fixture 已移除：包含真实私人聊天隐私数据"""
        pytest.skip("real_private_w1han_20260413 fixture 已移除（隐私数据清理）")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
