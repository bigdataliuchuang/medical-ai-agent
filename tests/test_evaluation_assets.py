from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_question_set_has_twenty_jsonl_records() -> None:
    questions_path = ROOT / "evaluation" / "questions.jsonl"
    records = [json.loads(line) for line in questions_path.read_text(encoding="utf-8").splitlines() if line]

    assert len(records) >= 20
