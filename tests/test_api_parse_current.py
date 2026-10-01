"""/api/parse と /api/parse-batch の正常系の出力を記録する。

ここにある入力の title・deadline・raw_text は、今後の修正でも変えない約束。
（応答に項目が増えるのはよい。既存の項目の値が変わったらテストが落ちる）

カテゴリ（category）は B27 から設定（JSON）で決める。カテゴリ名はコードに書かない。
- 見本の設定（公開している categories.sample.json。何も渡さないときに使う）での値と、
- 実物に似せた架空の設定（tests/fixtures/categories_reallike.json）での値を、両方記録する。
  架空の設定のカテゴリは番号（0〜3 = 設定の順）で書く。前の Category の4つと同じ順
  （0 = お寺の用事・1 = 団体1・2 = 団体2・3 = 個人）で、B27 の前と同じカテゴリになる。
"""
from __future__ import annotations

import pytest

FIELDS = ("title", "deadline", "category", "raw_text")

# (入力, 題名, 期限, 見本の設定のカテゴリ, 架空の設定のカテゴリの番号)
NORMAL_CASES = [
    ("会議資料の準備 (3/15まで)", "会議資料の準備", "2027-03-15T00:00:00+09:00", "仕事", 1),
    ("法要の準備 (3/15まで)", "法要の準備", "2027-03-15T00:00:00+09:00", "暮らし", 0),
    ("御詠歌の稽古 (5月中)", "御詠歌の稽古", "2027-05-31T00:00:00+09:00", "学び", 2),
    ("本堂の掃除 (早め)", "本堂の掃除", "2026-10-04T00:00:00+09:00", "暮らし", 0),
    ("病院の予約 (至急)", "病院の予約", "2026-10-02T00:00:00+09:00", "暮らし", 3),
    ("買い物 (来週まで)", "買い物", "2026-10-11T00:00:00+09:00", "暮らし", 3),
    ("メモを書く", "メモを書く", None, "暮らし", 3),
]


def pick(body: dict) -> dict:
    return {key: body[key] for key in FIELDS}


def expected_body(case: tuple, category: str) -> dict:
    text, title, deadline, _, _ = case
    return {"title": title, "deadline": deadline, "category": category, "raw_text": text}


@pytest.mark.parametrize("case", NORMAL_CASES, ids=[case[0] for case in NORMAL_CASES])
def test_parse_normal_cases_with_sample_config(client, frozen_now, case):
    response = client.post("/api/parse", json={"text": case[0]})
    assert response.status_code == 200
    assert pick(response.json()) == expected_body(case, case[3])


@pytest.mark.parametrize("case", NORMAL_CASES, ids=[case[0] for case in NORMAL_CASES])
def test_parse_normal_cases_with_reallike_config(client, frozen_now, reallike_categories, case):
    response = client.post("/api/parse", json={"text": case[0]})
    assert response.status_code == 200
    assert pick(response.json()) == expected_body(case, reallike_categories.names[case[4]])


def test_parse_batch_normal_cases_keep_order_and_skip_blank_lines(client, frozen_now):
    texts = [case[0] for case in NORMAL_CASES]
    response = client.post("/api/parse-batch", json={"tasks": [texts[0], "", "   ", *texts[1:]]})
    assert response.status_code == 200
    body = response.json()
    assert [pick(item) for item in body] == [expected_body(case, case[3]) for case in NORMAL_CASES]


def test_parse_batch_rejects_non_list(client):
    response = client.post("/api/parse-batch", json={"tasks": "メモ"})
    assert response.status_code == 422


def test_parse_rejects_missing_text(client):
    response = client.post("/api/parse", json={})
    assert response.status_code == 422
