#!/usr/bin/env python3
"""
wechat_rpa 模块化测试

测试各个独立模块的功能
"""

import os
import sys
import unittest
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wechat_rpa.ocr import VisionOCR, OCRElement
from wechat_rpa.parser import WeChatParser, ChatItem, ChatMessage
from wechat_rpa.storage import MessageStore, StoredMessage


class TestOCRModule(unittest.TestCase):
    """测试 OCR 模块"""
    
    @classmethod
    def setUpClass(cls):
        cls.ocr = VisionOCR()
        cls.fixture_dir = Path(__file__).parent.parent.parent / "tests" / "fixtures"
    
    def test_recognize_basic(self):
        """测试基本识别功能"""
        image_path = self.fixture_dir / "current.png"
        if not image_path.exists():
            self.skipTest("测试图片不存在")
        
        elements = self.ocr.recognize(str(image_path))
        
        # 验证结果
        self.assertIsInstance(elements, list)
        self.assertGreater(len(elements), 0, "应该识别到文本")
        
        # 验证元素结构
        for elem in elements:
            self.assertIsInstance(elem, OCRElement)
            self.assertIsInstance(elem.text, str)
            self.assertGreater(len(elem.text), 0)
            self.assertIsInstance(elem.confidence, float)
            self.assertGreater(elem.confidence, 0)
    
    def test_recognize_multiple_images(self):
        """测试多张图片识别"""
        test_images = [
            "current.png",
            "private_w1han.png",
            "medium_scene.png"
        ]
        
        for img_name in test_images:
            image_path = self.fixture_dir / img_name
            if not image_path.exists():
                continue
            
            with self.subTest(image=img_name):
                elements = self.ocr.recognize(str(image_path))
                self.assertGreater(len(elements), 0, f"{img_name} 应该识别到文本")


class TestParserModule(unittest.TestCase):
    """测试解析模块"""
    
    @classmethod
    def setUpClass(cls):
        cls.parser = WeChatParser()
        cls.ocr = VisionOCR()
        cls.fixture_dir = Path(__file__).parent.parent.parent / "tests" / "fixtures"
    
    def test_parse_chat_list(self):
        """测试聊天列表解析"""
        image_path = self.fixture_dir / "current.png"
        if not image_path.exists():
            self.skipTest("测试图片不存在")
        
        # OCR 识别
        elements = self.ocr.recognize(str(image_path))
        
        # 重新初始化 parser（使用正确尺寸）
        parser = WeChatParser(
            image_width=self.ocr.image_width,
            image_height=self.ocr.image_height
        )
        
        # 分离左侧元素
        left_elements = [e for e in elements if e.x < 300]
        chat_items = parser._parse_chat_list(left_elements)
        
        # 验证
        self.assertIsInstance(chat_items, list)
        self.assertGreaterEqual(len(chat_items), 1, "应该识别到至少1个聊天")
        
        # 验证第一个聊天
        first = chat_items[0]
        self.assertIsInstance(first, ChatItem)
        self.assertIsInstance(first.nickname, str)
        self.assertGreater(len(first.nickname), 0)
    
    def test_parse_chat_area(self):
        """测试聊天区域解析"""
        image_path = self.fixture_dir / "current.png"
        if not image_path.exists():
            self.skipTest("测试图片不存在")
        
        elements = self.ocr.recognize(str(image_path))
        
        parser = WeChatParser(
            image_width=self.ocr.image_width,
            image_height=self.ocr.image_height
        )
        
        right_elements = [e for e in elements if e.x >= 300]
        chat_name, messages, is_group = parser._parse_chat_area(
            right_elements, str(image_path)
        )
        
        # 验证聊天名称
        self.assertIsInstance(chat_name, str)
        self.assertGreater(len(chat_name), 0)
        
        # 验证消息
        self.assertIsInstance(messages, list)
        
        if messages:
            first_msg = messages[0]
            self.assertIsInstance(first_msg, ChatMessage)
            self.assertIn(first_msg.sender_type, ['self', 'other'])
    
    def test_nickname_detection(self):
        """测试昵称检测"""
        parser = WeChatParser()
        
        # 有效昵称
        self.assertTrue(parser._is_likely_nickname("wanglc"))
        self.assertTrue(parser._is_likely_nickname("张三"))
        
        # 无效昵称
        self.assertFalse(parser._is_likely_nickname(""))
        self.assertFalse(parser._is_likely_nickname("[图片]"))
        self.assertFalse(parser._is_likely_nickname("http://example.com"))
        self.assertFalse(parser._is_likely_nickname("12:34"))


class TestStorageModule(unittest.TestCase):
    """测试存储模块"""
    
    def setUp(self):
        """每个测试前创建新的存储实例"""
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.store = MessageStore(storage_dir=self.temp_dir)
    
    def tearDown(self):
        """每个测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_message_hash(self):
        """测试消息哈希生成"""
        msg = StoredMessage(
            text="测试消息",
            sender="user1",
            sender_type="other",
            chat_name="测试群"
        )
        
        # 验证哈希生成
        self.assertIsInstance(msg.message_hash, str)
        self.assertEqual(len(msg.message_hash), 32)  # MD5 长度
    
    def test_duplicate_detection(self):
        """测试重复检测"""
        msg1 = StoredMessage(
            text="相同内容",
            sender="user",
            sender_type="other",
            chat_name="群聊"
        )
        
        # 添加第一条
        new_msgs = self.store.add_messages([msg1])
        self.assertEqual(len(new_msgs), 1)
        
        # 添加相同内容（应被去重）
        msg2 = StoredMessage(
            text="相同内容",
            sender="user",
            sender_type="other",
            chat_name="群聊"
        )
        new_msgs = self.store.add_messages([msg2])
        self.assertEqual(len(new_msgs), 0, "重复消息应该被过滤")
    
    def test_stats(self):
        """测试统计功能"""
        # 添加测试消息
        messages = [
            StoredMessage(text="msg1", sender="自己", sender_type="self", chat_name="群1"),
            StoredMessage(text="msg2", sender="user", sender_type="other", chat_name="群1"),
            StoredMessage(text="msg3", sender="user", sender_type="other", chat_name="群2"),
        ]
        
        self.store.add_messages(messages)
        
        stats = self.store.get_stats()
        
        self.assertEqual(stats["total_messages"], 3)
        self.assertEqual(stats["unique_chats"], 2)
        self.assertEqual(stats["self_messages"], 1)
        self.assertEqual(stats["other_messages"], 2)


class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = Path(__file__).parent.parent.parent / "tests" / "fixtures"
        cls.test_images = [
            ("current.png", "王老板们和小天才"),
            ("private_w1han.png", "W1han"),
            ("medium_scene.png", "王老板们和小天才"),
        ]
    
    def test_full_pipeline(self):
        """测试完整流程：OCR -> Parser"""
        ocr = VisionOCR()
        
        for img_name, expected_chat in self.test_images:
            image_path = self.fixture_dir / img_name
            if not image_path.exists():
                continue
            
            with self.subTest(image=img_name):
                # OCR
                elements = ocr.recognize(str(image_path))
                self.assertGreater(len(elements), 0)
                
                # Parser
                parser = WeChatParser(
                    image_width=ocr.image_width,
                    image_height=ocr.image_height
                )
                layout = parser.parse(elements, str(image_path))
                
                # 验证
                self.assertIsInstance(layout.chat_name, str)
                self.assertGreater(len(layout.chat_name), 0)
                
                # 验证聊天列表
                self.assertIsInstance(layout.chat_items, list)
                
                # 验证消息
                self.assertIsInstance(layout.messages, list)


def run_tests():
    """运行所有测试"""
    print("=" * 70)
    print("🧪 wechat_rpa 模块测试")
    print("=" * 70)
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestOCRModule))
    suite.addTests(loader.loadTestsFromTestCase(TestParserModule))
    suite.addTests(loader.loadTestsFromTestCase(TestStorageModule))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出汇总
    print("\n" + "=" * 70)
    print("📊 测试结果汇总")
    print("=" * 70)
    print(f"测试总数: {result.testsRun}")
    print(f"通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    
    if result.wasSuccessful():
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n❌ 有测试失败")
        return 1


if __name__ == "__main__":
    exit(run_tests())
