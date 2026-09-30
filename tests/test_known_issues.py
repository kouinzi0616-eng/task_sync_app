"""直す予定の不具合を「今の挙動」として記録する（B25 で直し、回帰テストに置き換える）。"""
from __future__ import annotations


def test_nonexistent_date_makes_parse_fail_with_500(client, frozen_now):
    response = client.post("/api/parse", json={"text": "資料 (2/30まで)"})
    assert response.status_code == 500
    # 内部の例外文がそのまま返っている
    assert "day is out of range" in response.json()["detail"]


def test_one_bad_line_makes_whole_batch_fail(client, frozen_now):
    response = client.post("/api/parse-batch", json={"tasks": ["法要の準備 (3/15まで)", "資料 (2/30まで)"]})
    assert response.status_code == 500


def test_full_width_parentheses_are_not_recognized(client, frozen_now):
    body = client.post("/api/parse", json={"text": "法要の準備（3/15まで）"}).json()
    assert body["deadline"] is None
    assert body["title"] == "法要の準備（3/15まで）"


def test_title_keeps_due_part_unless_it_matches_fixed_examples(client, frozen_now):
    body = client.post("/api/parse", json={"text": "書類の提出 (4/1まで)"}).json()
    assert body["deadline"] == "2027-04-01T00:00:00+09:00"
    assert body["title"] == "書類の提出 (4/1まで)"


def test_empty_text_is_accepted(client):
    response = client.post("/api/parse", json={"text": ""})
    assert response.status_code == 200
    assert response.json()["title"] == ""


def test_cors_allows_any_origin_with_credentials(client):
    response = client.options(
        "/api/parse",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "https://evil.example"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_api_docs_are_public(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
