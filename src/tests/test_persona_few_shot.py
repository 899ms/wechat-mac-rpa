import hashlib
import json

from src.models.base import ChatMessage, SenderType
from src.reply.few_shot import PersonaFewShotRetriever
from src.reply.generator import ReplyGenerator


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_group_retrieval_prefers_same_chat(tmp_path):
    path = tmp_path / "examples.jsonl"
    chat_name = "柚子群2"
    same_chat_id = "chat_" + hashlib.sha256(chat_name.encode()).hexdigest()[:10]
    _write_rows(path, [
        {"id": "other", "relationship": "group", "chat_id": "chat_other", "context": ["股票跌了"], "reply": ["躺平"]},
        {"id": "same", "relationship": "group", "chat_id": same_chat_id, "context": ["晚上吃啥"], "reply": ["喝西北风"]},
        {"id": "private", "relationship": "friend", "chat_id": "chat_private", "context": ["股票跌了"], "reply": ["知道了"]},
    ])

    rows = PersonaFewShotRetriever(path).retrieve("股票跌了", chat_name, is_group=True, limit=2)

    assert [row["id"] for row in rows] == ["same", "other"]


def test_private_retrieval_excludes_group_examples(tmp_path):
    path = tmp_path / "examples.jsonl"
    _write_rows(path, [
        {"id": "group", "relationship": "group", "chat_id": "g", "context": ["在吗"], "reply": ["咋"]},
        {"id": "friend", "relationship": "friend", "chat_id": "f", "context": ["在吗"], "reply": ["咋啦"]},
    ])

    rows = PersonaFewShotRetriever(path).retrieve("在吗", "朋友", is_group=False, limit=8)

    assert [row["id"] for row in rows] == ["friend"]


def test_render_has_fact_isolation_and_budget(tmp_path):
    rows = [
        {"id": "one", "context": ["在吗"], "reply": ["咋啦"]},
        {"id": "two", "context": ["x" * 100], "reply": ["y" * 100]},
    ]

    content, ids = PersonaFewShotRetriever.render(rows, max_chars=170)

    assert ids == ["one"]
    assert "不是当前对话事实" in content
    assert "本人：咋啦" in content


def test_missing_file_degrades_to_empty(tmp_path):
    retriever = PersonaFewShotRetriever(tmp_path / "missing.jsonl")

    assert retriever.retrieve("你好", "朋友", is_group=False) == []


def test_generator_injects_examples_and_records_ids(tmp_path, monkeypatch):
    path = tmp_path / "examples.jsonl"
    _write_rows(path, [
        {"id": "style_one", "relationship": "friend", "chat_id": "f", "context": ["在吗"], "reply": ["咋啦"]},
    ])
    monkeypatch.setenv("PERSONA_FEW_SHOT_PATH", str(path))
    monkeypatch.setenv("ENABLE_PERSONA_FEW_SHOTS", "1")

    class LLM:
        def __init__(self):
            self.responses = ['{"skills": []}', '{"replies": ["在的"]}']

        def chat(self, messages, tools=None, **kwargs):
            return self.responses.pop(0)

    message = ChatMessage(text="在吗", sender="朋友", sender_type=SenderType.OTHER, chat_name="朋友")
    generator = ReplyGenerator(llm_client=LLM())
    generator.enable_self_refine = False

    replies = generator.generate([message], [message], is_group=False)

    assert replies == ["在的"]
    assert generator.last_few_shot_ids == ["style_one"]
    assert "本人真实聊天风格示例" in generator.last_user_prompt
    assert any(item.get("type") == "persona_few_shot" for item in generator.last_generation_trace)
