"""直す予定の不具合を「今の挙動」として記録する（B25 で直し、回帰テストに置き換える）。"""
from __future__ import annotations


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
