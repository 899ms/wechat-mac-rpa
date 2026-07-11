import json

from scripts.build_persona_few_shots import extract_candidates, extract_chat_backup, select_balanced, write_outputs


def _message(text, sent, timestamp, sender="contact"):
    return {
        "content": text,
        "createTime": timestamp,
        "isSend": sent,
        "localType": 1,
        "senderDisplayName": sender,
        "senderUsername": sender,
    }


def test_extracts_and_anonymizes_conversation(tmp_path):
    export_dir = tmp_path / "exports"
    wiki_dir = tmp_path / "wiki"
    export_dir.mkdir()
    wiki_dir.mkdir()
    payload = {
        "session": {"displayName": "张三"},
        "messages": [
            _message("张三你晚上来吗", False, 1, "张三"),
            _message("来呀，晚点到", True, 2, "本人"),
        ],
    }
    (export_dir / "私聊_张三.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    rows = extract_candidates(export_dir, wiki_dir)

    assert len(rows) == 1
    assert rows[0].context == ["[联系人]你晚上来吗"]
    assert rows[0].replies == ["来呀，晚点到"]
    assert "张三" not in rows[0].chat_id


def test_rejects_sensitive_conversation(tmp_path):
    export_dir = tmp_path / "exports"
    wiki_dir = tmp_path / "wiki"
    export_dir.mkdir()
    wiki_dir.mkdir()
    payload = {
        "session": {},
        "messages": [
            _message("验证码是123456", False, 1),
            _message("收到", True, 2),
        ],
    }
    (export_dir / "私聊_联系人.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert extract_candidates(export_dir, wiki_dir) == []


def test_balanced_selection_and_outputs(tmp_path):
    export_dir = tmp_path / "exports"
    wiki_dir = tmp_path / "wiki"
    export_dir.mkdir()
    wiki_dir.mkdir()
    for index in range(4):
        payload = {
            "session": {},
            "messages": [
                _message(f"问题{index}", False, index * 2 + 1),
                _message(f"回答{index}呀", True, index * 2 + 2),
            ],
        }
        (export_dir / f"私聊_联系人{index}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    candidates = extract_candidates(export_dir, wiki_dir)
    selected = select_balanced(candidates, 3)
    write_outputs(selected, tmp_path / "out", len(candidates))

    lines = (tmp_path / "out" / "persona_examples.jsonl").read_text(encoding="utf-8").splitlines()
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert len(lines) == 3
    assert report["selected_count"] == 3
    assert report["external_model_used"] is False


def test_extracts_self_from_chat_backup(tmp_path):
    path = tmp_path / "幽默群.json"
    payload = {
        "chat_name": "幽默群",
        "messages": [
            {**_message("今天又跌了", False, 1, "群友"), "sender_type": "other", "message_type": "text", "text": "今天又跌了"},
            {**_message("韭菜申请躺平😂", True, 2, "自己"), "sender_type": "self", "message_type": "text", "text": "韭菜申请躺平😂"},
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    rows = extract_chat_backup(path)

    assert len(rows) == 1
    assert rows[0].relation == "group"
    assert rows[0].priority is True
    assert rows[0].replies == ["韭菜申请躺平😂"]
