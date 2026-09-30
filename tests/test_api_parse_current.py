"""/api/parse と /api/parse-batch の正常系の出力を記録する。

ここにある入力の title・deadline・category・raw_text は、今後の修正でも変えない約束。
（応答に項目が増えるのはよい。既存の4項目の値が変わったらテストが落ちる）
カテゴリは名前を直接書かず、backend.models.Category の値で比べる。
"""
from __future__ import annotations

import pytest

from backend.models import Category

FIELDS = ("title", "deadline", "category", "raw_text")

NORMAL_CASES = [
    (
        "会議資料の準備 (3/15まで)",
        {"title": "会議資料の準備", "deadline": "2027-03-15T00:00:00+09:00", "category": Category.SEIHOUKAI},
    ),
    (
        "法要の準備 (3/15まで)",
        {"title": "法要の準備", "deadline": "2027-03-15T00:00:00+09:00", "category": Category.TEMPLE},
    ),
    (
        "御詠歌の稽古 (5月中)",
        {"title": "御詠歌の稽古", "deadline": "2027-05-31T00:00:00+09:00", "category": Category.EIDOUBU},
    ),
    (
        "本堂の掃除 (早め)",
        {"title": "本堂の掃除", "deadline": "2026-10-04T00:00:00+09:00", "category": Category.TEMPLE},
    ),
    (
        "病院の予約 (至急)",
        {"title": "病院の予約", "deadline": "2026-10-02T00:00:00+09:00", "category": Category.PERSONAL},
    ),
    (
        "買い物 (来週まで)",
        {"title": "買い物", "deadline": "2026-10-11T00:00:00+09:00", "category": Category.PERSONAL},
    ),
    (
        "メモを書く",
        {"title": "メモを書く", "deadline": None, "category": Category.PERSONAL},
    ),
]


def pick(body: dict) -> dict:
    return {key: body[key] for key in FIELDS}


def expected_body(text: str, expected: dict) -> dict:
    return {
        "title": expected["title"],
        "deadline": expected["deadline"],
        "category": expected["category"].value,
        "raw_text": text,
    }


@pytest.mark.parametrize(("text", "expected"), NORMAL_CASES)
def test_parse_normal_cases(client, frozen_now, text, expected):
    response = client.post("/api/parse", json={"text": text})
    assert response.status_code == 200
    assert pick(response.json()) == expected_body(text, expected)


def test_parse_batch_normal_cases_keep_order_and_skip_blank_lines(client, frozen_now):
    texts = [text for text, _ in NORMAL_CASES]
    response = client.post("/api/parse-batch", json={"tasks": [texts[0], "", "   ", *texts[1:]]})
    assert response.status_code == 200
    body = response.json()
    assert [pick(item) for item in body] == [
        expected_body(text, expected) for text, expected in NORMAL_CASES
    ]


def test_parse_batch_rejects_non_list(client):
    response = client.post("/api/parse-batch", json={"tasks": "メモ"})
    assert response.status_code == 422


def test_parse_rejects_missing_text(client):
    response = client.post("/api/parse", json={})
    assert response.status_code == 422
