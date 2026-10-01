"""B28: 応答ヘッダ（CSP など）と、HTML を混ぜた架空の入力の扱い。

テストの文字列はすべて架空。外部には送信しない（TestClient だけを使う）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from backend import api

ROOT = Path(__file__).resolve().parent.parent

# 架空の攻撃文字列（画像の読み込み失敗でスクリプトを動かそうとする形）
XSS_IMG = '<img src=x onerror="window.__xss=1">'
XSS_SCRIPT = "<script>window.__xss=2</script>"


def _csp_directives(value: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for part in value.split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0].lower()] = tokens[1:]
    return directives


def _assert_security_headers(response, *, with_csp: bool = True):
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-frame-options"] == "DENY"
    assert headers["cross-origin-opener-policy"] == "same-origin-allow-popups"
    assert "camera=()" in headers["permissions-policy"]
    if not with_csp:
        assert "content-security-policy" not in headers
        return
    csp = _csp_directives(headers["content-security-policy"])
    assert csp["default-src"] == ["'self'"]
    assert csp["script-src"] == ["'self'"]
    assert csp["style-src"] == ["'self'"]
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["object-src"] == ["'none'"]
    assert "base-uri" in csp
    joined = headers["content-security-policy"]
    for loose in ("'unsafe-inline'", "'unsafe-eval'", "data:", "*"):
        assert loose not in joined.split(), loose


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/index.html",
        "/app.js",
        "/app.css",
        "/sw.js",
        "/manifest.json",
        "/icon-192.png",
        "/favicon.ico",
        "/static/index.html",
        "/api/health",
    ],
)
def test_get_responses_have_security_headers(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    _assert_security_headers(response)


def test_error_and_post_responses_have_security_headers(client):
    _assert_security_headers(client.get("/no-such-page"))
    _assert_security_headers(client.post("/api/parse", json={"text": "架空の用事 (3/15まで)"}))
    _assert_security_headers(client.post("/api/parse", json={"text": ""}))  # 422


def test_headers_are_not_duplicated(client):
    response = client.get("/")
    for name in api.SECURITY_HEADERS:
        assert len(response.headers.get_list(name)) == 1, name


def test_html_in_task_text_is_returned_as_plain_json(client):
    tasks = [
        f"{XSS_IMG}架空の資料作り (3/15まで)",
        f"架空の打ち合わせ ({XSS_IMG})",
        f"{XSS_SCRIPT} 架空の片付け",
    ]
    response = client.post("/api/parse-batch", json={"tasks": tasks})
    assert response.status_code == 200
    # JSON として返す（HTML としては返さない）。画面は textContent で表示する
    assert response.headers["content-type"].startswith("application/json")
    _assert_security_headers(response)
    rows = response.json()
    assert [row["raw_text"] for row in rows] == tasks
    assert XSS_IMG in rows[0]["title"]
    assert rows[0]["deadline"] is not None
    assert XSS_SCRIPT in rows[2]["title"]


def test_html_in_url_is_not_reflected_as_html(client):
    response = client.get(f"/{XSS_IMG}")
    assert response.status_code == 404
    assert not response.headers["content-type"].startswith("text/html")
    _assert_security_headers(response)


def test_api_docs_page_has_no_csp_only_when_enabled():
    """ENABLE_API_DOCS=1 のときだけ /docs に CSP を付けない（外部の JS を使うため）。ほかの画面には付ける。"""
    code = textwrap.dedent(
        """
        import warnings
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
        from backend.api import app

        with TestClient(app) as client:
            docs = client.get("/docs")
            root = client.get("/")
            print(docs.status_code, "content-security-policy" in docs.headers,
                  docs.headers.get("x-content-type-options"),
                  "content-security-policy" in root.headers)
        """
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "ENABLE_API_DOCS": "1"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["200", "False", "nosniff", "True"]


def test_api_docs_are_off_by_default_and_csp_applies(client):
    response = client.get("/docs")
    assert response.status_code == 404
    _assert_security_headers(response)
