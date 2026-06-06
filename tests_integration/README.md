# 微信 OCR 测试套件

## 测试框架

当前测试基于 `pytest`，覆盖 `src/` 模块化架构和 `tests_integration/` 外部测试套件。

## 运行测试

### 运行所有内部测试
```bash
python3 -m pytest src/tests/ -v
```

### 运行 OCR 质量 Benchmark（推荐）
```bash
# 使用缓存（快速回归，不调用 API）
python3 src/tests/test_ocr_quality_benchmark.py

# 调用真实 API（建立/更新缓存）
python3 src/tests/test_ocr_quality_benchmark.py --run-api
```

### 生成可视化报告
```bash
python3 scripts/generate_ocr_benchmark_report.py
# 输出: ocr_benchmark_report.html
```

### 运行集成测试
```bash
python3 tests_integration/test_integration.py
```

## 测试用例结构

每个测试用例包含两个文件：
- `{name}.png` - 微信截图
- `{name}.json` - 预期 OCR 结果（Ground Truth）

Fixture 存放在 `tests_integration/fixtures/` 下：
- `tests_integration/fixtures/` — 实时截图用例
- `tests_integration/fixtures/legacy/errors/` — 历史错误回归用例

## 当前测试用例

| 测试套件 | 位置 | 数量 | 说明 |
|---------|------|------|------|
| 内部单元测试 | `src/tests/` | 148+ | 模块化架构各层单元测试 |
| OCR 质量 Benchmark | `src/tests/test_ocr_quality_benchmark.py` | 33 | qwen3.6-flash API 精度验证 |
| 真实场景回归 | `tests_integration/test_real_scene_extraction.py` | - | 基于真实截图的回归验证 |

## 最新 Benchmark 指标（qwen3.6-flash + thinking）

| 指标 | 数值 |
|------|------|
| **通过率** | **81.8%** (27/33) |
| Chat Name 准确率 | 93.9% |
| Message Count 准确率 | 93.9% |
| Sender 平均准确率 | 88.7% |
| Sender 100%正确率 | 84.4% |
| Text 平均准确率 | 90.2% |

### 按类别

| 类别 | 通过 | 说明 |
|------|------|------|
| group_chat | 3/4 | 实时群聊截图 |
| legacy_group | 7/7 | 历史群聊回归用例 |
| legacy_private | 15/16 | 历史私聊回归用例 |
| private_chat | 2/2 | 实时私聊截图 |
| regression | 0/4 | 已知问题回归（API 侧待优化） |

## 添加回归测试

发现新的识别错误时：
1. 保存错误截图到 `tests_integration/fixtures/`
2. 编写同名 `.json` 描述预期结果
3. 运行 `python3 src/tests/test_ocr_quality_benchmark.py --run-api` 生成缓存
4. 重新生成报告验证

## 测试标准

- 聊天名称准确率 >= 90%
- 发送者类型识别率 >= 85%
- 消息数量准确率 >= 90%
- 消息内容准确率 >= 80%

## 文件位置

```
tests_integration/
├── README.md              # 本文件
├── test_integration.py    # 集成测试入口
├── test_real_scene_extraction.py  # 真实场景回归测试
├── fixtures/              # 测试用例目录
│   ├── *.png / *.json     # 实时截图用例
│   └── legacy/errors/     # 历史错误回归用例
└── ...
```

---

**历史说明**: 旧版 `test_ocr_v4.py`、`add_test_case.py` 及 `core/auto_bot_vision_ocr_v4.py` 已删除，由 `src/` 模块化架构 + pytest 完全替代。
