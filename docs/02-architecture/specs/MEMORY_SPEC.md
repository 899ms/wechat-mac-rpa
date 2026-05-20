# Memory Module Spec

## 1. 模块职责
管理 Bot 的长期记忆：用户 wiki、群 wiki、BM25 搜索、别名解析、外挂 overrides。

## 2. 功能需求 (FR)

- **FR-1**: `get_user_memory(user_name)`：读取用户 wiki（含别名合并 + 外挂 facts），返回压缩后的摘要。
- **FR-2**: `get_group_memory(group_name)`：读取群聊 wiki（含外挂 corrections）。
- **FR-3**: `update_user_wiki()` / `update_group_wiki()`：将更新任务加入队列，后台异步执行（LLM 生成新 wiki）。
- **FR-4**: `search_keyword(keyword)`：BM25 搜索所有 wiki，返回最相关的片段。命中本人返回完整 wiki，命中别人返回片段。
- **FR-5**: `search_related_mentions(text)`：扫描文本中提到的人名，加载这些人自己的 wiki。
- **FR-6**: 别名自动发现：从 LLM 生成的 wiki 中提取别名，保存到 `alias_suggestions/` 供人工审核。
- **FR-7**: 外挂配置加载：`aliases.json`、`facts.json`、`corrections.json`。

## 3. 非功能需求 (NFR)

- **NFR-1**: Wiki 更新异步执行，不阻塞主 tick 流程。
- **NFR-2**: Worker 线程每 5 秒检查队列，批量处理（每批最多 3 条，或积压超过 5 分钟的全部处理）。
- **NFR-3**: 个人 wiki 不超过 4000 字，群 wiki 不超过 4000 字。
- **NFR-4**: LLM 生成 wiki 带 3 次重试：处理 429 配额限制（指数退避）、400 输入超长（截断 conversation）。

## 4. 接口契约

### 输入
```python
MemoryEngine(llm_client=None)

get_user_memory(user_name: str, max_chars: int = 2000) -> str
get_group_memory(group_name: str, max_chars: int = 2000) -> str
update_user_wiki(user_name, chat_name, messages, bot_replies)
update_group_wiki(group_name, chat_name, messages, bot_replies)
search_keyword(keyword: str, max_chars: int = 6000) -> str
```

### 输出
- Wiki 摘要：Markdown 文本，可能包含 `（…记忆已截断）`
- 搜索结果：带标签的文本片段，如 `【某某的记忆】...`

## 5. 核心规则与约束

### 规则 1: 增量更新铁律——严禁删除现有内容
LLM prompt 明确要求：
- 严禁删除现有 wiki 中的任何内容（除非明确超过 7 天且属于"近期动态"）
- "本次对话未提及" ≠ "信息已过期"
- 所有事实必须标注来源

### 规则 2: 别名不能是其他人的主名
```python
if alias in existing_mains and alias != user_name:
    continue  # 不采纳
```
防止别名冲突导致 `get_user_memory` 加载到错误用户的 wiki。

### 规则 3: 区分陈述和疑问
以"吗"、"呢"、"?"结尾的句子是疑问，**严禁当作事实提取**。

### 规则 4: Facts 放在 Wiki 前面
`get_user_memory` 返回时，外挂 facts 放在 LLM 生成的 wiki 前面，确保截断时不丢失人工标注的关键信息。

### 规则 5: BM25 搜索本人优先
命中本人的 wiki 返回完整内容；命中其他人的只返回片段（防止无关 wiki 淹没 prompt）。

## 6. 错误处理

| 情况 | 处理 |
|------|------|
| LLM 生成失败（3 次重试后） | 记录 error，不更新 wiki |
| Wiki 文件读写失败 | 记录 warning，返回空字符串 |
| 别名解析冲突 | 优先匹配主名，冲突时记录 debug |

## 7. 依赖关系
- 依赖 LLM 客户端（wiki 更新时）
- 被 `src.bot.WeChatBot` 和 `src.reply.generator.ReplyGenerator` 调用
