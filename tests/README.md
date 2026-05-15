# 微信 OCR 测试套件

## 测试框架

当前测试基于 `pytest`，覆盖 `src/` 模块化架构和 `tests/` 外部测试套件。

## 运行测试

### 运行所有内部测试
```bash
python3 -m pytest src/tests/ -v
```

### 运行所有外部测试
```bash
python3 -m pytest tests/ -v
```

### 运行集成测试
```bash
python3 tests/test_integration.py
```

## 测试用例结构

每个测试用例包含两个文件：
- `{name}.png` - 微信截图
- `{name}.json` - 预期 OCR 结果

Fixture 存放在 `tests/fixtures/` 和 `src/tests/fixtures/` 下。

## 当前测试用例

| 测试套件 | 位置 | 数量 | 说明 |
|---------|------|------|------|
| 内部单元测试 | `src/tests/` | 148+ | 模块化架构各层单元测试 |
| 外部集成测试 | `tests/` | 54+ | 端到端场景测试 |
| 真实场景回归 | `tests/test_real_scene_extraction.py` | - | 基于真实截图的回归验证 |

## 添加回归测试

发现新的识别错误时：
1. 保存错误截图到 `tests/fixtures/errors/`
2. 编写同名 `.json` 描述预期结果
3. 在对应测试模块中添加回归测试用例

## 测试标准

- 聊天名称准确率 >= 95%
- 发送者类型识别率 >= 90%
- 消息数量必须完全一致
- 消息内容相似度 > 90%

## 文件位置

```
tests/
├── README.md              # 本文件
├── test_integration.py    # 集成测试入口
├── test_real_scene_extraction.py  # 真实场景回归测试
├── run_tests.sh           # ⚠️ 已失效（依赖已删除的 V4 代码）
├── regression_suite.py    # 模块化回归测试（部分可用）
├── fixtures/              # 测试用例目录
│   ├── errors/            # 错误回归用例
│   └── regression/        # 回归测试截图
└── ...
```

---

**历史说明**: 旧版 `test_ocr_v4.py`、`add_test_case.py` 及 `core/auto_bot_vision_ocr_v4.py` 已删除，由 `src/` 模块化架构 + pytest 完全替代。
