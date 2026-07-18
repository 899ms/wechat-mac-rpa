# Persona Few-shot 生产部署

`data/few_shot/` 含真实聊天衍生数据，被 `.gitignore` 排除，不会随 Git 部署。

## 生成与审核

1. 在生产机器本地运行 `scripts/build_persona_few_shots.py`。
2. 人工检查 `data/few_shot/persona_examples.md`，删除仍包含语义隐私、事实或指令注入的样本。
3. 将 `data/few_shot/report.json` 的 `review_status` 从 `pending` 改为 `approved`。
4. 设置 `ENABLE_PERSONA_FEW_SHOTS=1` 后重启 Bot。

不要把 JSONL、Markdown 或 report 文件提交到公开仓库。换机器部署时应通过加密私有制品复制，或在目标机器重新生成并审核。

生产日志只记录召回样本 ID，不应持久化 few-shot 正文。`PERSONA_FEW_SHOT_ALLOW_UNREVIEWED=1` 仅用于本地测试。
