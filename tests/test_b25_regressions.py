"""B25（解析 API の即時修正）の回帰テスト。

基準日は 2026-10-01（木）JST に固定。文字列はすべて架空。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import pytest

import backend.api as api
from backend.date_parser import JST, parse_date, parse_deadline
from backend.models import Category

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=JST)
ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------
# (1) 存在しない月日は例外にせず「期限なし＋警告」
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "資料 (2/30まで)",
        "資料 (2/29まで)",  # 2026年・2027年は平年
        "資料 (13/1まで)",
        "資料 (0/5まで)",
        "資料 (3/0まで)",
        "資料 (13月中)",
        "資料 (0月中)",
    ],
)
def test_nonexistent_dates_return_no_deadline_with_warning(text):
    result = parse_deadline(text, now=NOW)
    assert result.deadline is None
    assert result.title == "資料"
    assert len(result.warnings) == 1
    assert "存在しない日付" in result.warnings[0]
    assert parse_date(text, now=NOW) is None


def test_feb_29_in_leap_year_is_valid():
    result = parse_deadline("資料 (2/29まで)", now=datetime(2028, 1, 10, tzinfo=JST))
    assert result.deadline.isoformat() == "2028-02-29T00:00:00+09:00"
    assert result.warnings == ()


def test_feb_29_just_passed_in_leap_year_is_overdue_this_year():
    # B26 仕様変更: 旧は「過ぎていれば翌年」→ 2029-02-29 が無いので期限なし＋警告だった。
    # 直近（猶予 62日の内）の過去日は今年のまま「期限切れ」にする
    result = parse_deadline("資料 (2/29まで)", now=datetime(2028, 3, 5, tzinfo=JST))
    assert result.deadline.isoformat() == "2028-02-29T00:00:00+09:00"
    assert result.overdue is True
    assert result.needs_review is True


def test_feb_29_long_passed_in_leap_year_warns_instead_of_crashing():
    # 猶予を過ぎたので翌年にしたいが、2029-02-29 は存在しない → 例外にせず期限なし＋警告
    result = parse_deadline("資料 (2/29まで)", now=datetime(2028, 6, 1, tzinfo=JST))
    assert result.deadline is None
    assert len(result.warnings) == 1
    assert "存在しない日付" in result.warnings[0]


# ------------------------------------------------------------
# (3) 期限の括弧は全角・半角の両方。題名から期限の部分を除く
# ------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "title", "deadline"),
    [
        ("法要の準備（3/15まで）", "法要の準備", "2027-03-15"),
        ("法要の準備 (3/15まで)", "法要の準備", "2027-03-15"),
        ("法要の準備（３／１５まで）", "法要の準備", "2027-03-15"),  # 全角の数字と斜線
        ("法要の準備（3/15まで)", "法要の準備", "2027-03-15"),  # 全角と半角が混ざっても読む
        ("書類の提出 (4/1まで)", "書類の提出", "2027-04-01"),  # 例示に無い日付も題名から除く
        ("書類の提出（5月中）", "書類の提出", "2027-05-31"),
        ("書類の提出（早め）", "書類の提出", "2026-10-04"),
        ("書類の提出（至急）", "書類の提出", "2026-10-02"),
        ("書類の提出 (来週)", "書類の提出", "2026-10-11"),
        ("書類 (4/1まで) の提出", "書類  の提出", "2027-04-01"),  # 行の途中でも除く
    ],
)
def test_due_part_is_found_and_removed_from_title(text, title, deadline):
    result = parse_deadline(text, now=NOW)
    assert result.title == title
    assert result.deadline.date().isoformat() == deadline
    assert result.warnings == ()


def test_parentheses_that_are_not_due_expressions_stay_in_title():
    result = parse_deadline("資料（第2版）の印刷", now=NOW)
    assert result.deadline is None
    assert result.title == "資料（第2版）の印刷"


def test_due_only_line_keeps_text_as_title_with_warning():
    result = parse_deadline("(4/1まで)", now=NOW)
    assert result.deadline.isoformat() == "2027-04-01T00:00:00+09:00"
    assert result.title == "(4/1まで)"
    assert result.warnings == ("題名がありません（期限だけが書かれています）",)


# ------------------------------------------------------------
# API から見た回帰（仕様に列挙された入力）
# ------------------------------------------------------------

def test_api_nonexistent_date_is_200_with_warning(client, frozen_now):
    response = client.post("/api/parse", json={"text": "資料 (2/30まで)"})
    assert response.status_code == 200
    body = response.json()
    assert body["deadline"] is None
    assert body["title"] == "資料"
    assert body["raw_text"] == "資料 (2/30まで)"
    assert body["warnings"] and "存在しない日付" in body["warnings"][0]


def test_api_full_width_parentheses(client, frozen_now):
    body = client.post("/api/parse", json={"text": "法要の準備（3/15まで）"}).json()
    assert body["title"] == "法要の準備"
    assert body["deadline"] == "2027-03-15T00:00:00+09:00"
    assert body["category"] == Category.TEMPLE.value
    assert body["warnings"] == []


def test_api_due_only_line(client, frozen_now):
    response = client.post("/api/parse", json={"text": "(4/1まで)"})
    assert response.status_code == 200
    body = response.json()
    assert body["deadline"] == "2027-04-01T00:00:00+09:00"
    assert body["title"] == "(4/1まで)"


def test_api_normal_case_has_no_warnings(client, frozen_now):
    body = client.post("/api/parse", json={"text": "法要の準備 (3/15まで)"}).json()
    assert body["warnings"] == []


def test_api_batch_with_valid_and_invalid_lines_is_200(client, frozen_now):
    response = client.post(
        "/api/parse-batch",
        json={"tasks": ["法要の準備 (3/15まで)", "資料 (2/30まで)", "書類の提出（4/1まで）"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body] == ["法要の準備", "資料", "書類の提出"]
    assert [item["deadline"] for item in body] == [
        "2027-03-15T00:00:00+09:00",
        None,
        "2027-04-01T00:00:00+09:00",
    ]
    assert [bool(item["warnings"]) for item in body] == [False, True, False]


# ------------------------------------------------------------
# (2) 一括解析は行ごとに成否を返し、1行の失敗で全体を500にしない
# ------------------------------------------------------------

def _classify_or_fail(text):
    if "失敗させる行" in text:
        raise RuntimeError("内部の詳細-0000")
    return Category.PERSONAL


def test_api_batch_reports_failure_per_row(client, frozen_now, monkeypatch):
    monkeypatch.setattr(api, "classify_category", _classify_or_fail)
    response = client.post(
        "/api/parse-batch",
        json={"tasks": ["資料A (3/15まで)", "失敗させる行 (3/15まで)", "資料B (2/30まで)"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["ok"] for item in body] == [True, False, True]
    failed = body[1]
    assert failed["error"] == api.ROW_ERROR_MESSAGE
    assert failed["raw_text"] == "失敗させる行 (3/15まで)"
    assert failed["deadline"] is None
    assert "内部の詳細" not in response.text
    assert body[0]["error"] is None
    assert body[2]["warnings"]


# ------------------------------------------------------------
# (4) 入力の上限。空文字は Field の制約で 422
# ------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_api_parse_rejects_empty_or_blank_text(client, text):
    assert client.post("/api/parse", json={"text": text}).status_code == 422


def test_api_parse_length_limit(client, frozen_now):
    ok = "あ" * api.MAX_TEXT_LENGTH
    assert client.post("/api/parse", json={"text": ok}).status_code == 200
    too_long = ok + "あ"
    assert client.post("/api/parse", json={"text": too_long}).status_code == 422


def test_api_batch_count_limit(client, frozen_now):
    ok = ["メモ"] * api.MAX_BATCH_TASKS
    assert client.post("/api/parse-batch", json={"tasks": ok}).status_code == 200
    assert client.post("/api/parse-batch", json={"tasks": ok + ["メモ"]}).status_code == 422


def test_api_batch_line_length_limit(client):
    too_long = "あ" * (api.MAX_TEXT_LENGTH + 1)
    response = client.post("/api/parse-batch", json={"tasks": ["メモ", too_long]})
    assert response.status_code == 422


def test_api_batch_still_skips_blank_lines(client, frozen_now):
    response = client.post("/api/parse-batch", json={"tasks": ["", "  ", "メモ"]})
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["メモ"]


# ------------------------------------------------------------
# (5) 500 の応答に内部の例外文を載せない。ログは件数だけで、題名を出さない
# ------------------------------------------------------------

def test_api_parse_500_hides_internal_error(client, monkeypatch):
    def broken(text):
        raise RuntimeError("内部の詳細-0000")

    monkeypatch.setattr(api, "parse_deadline", broken)
    response = client.post("/api/parse", json={"text": "資料 (3/15まで)"})
    assert response.status_code == 500
    assert response.json() == {"detail": api.PARSE_ERROR_MESSAGE}
    assert "内部の詳細" not in response.text


def test_logs_have_counts_but_no_titles(client, frozen_now, monkeypatch, caplog):
    monkeypatch.setattr(api, "classify_category", _classify_or_fail)
    caplog.set_level(logging.INFO, logger="backend.api")

    client.post("/api/parse", json={"text": "架空の題名その一 (3/15まで)"})
    client.post(
        "/api/parse-batch",
        json={"tasks": ["架空の題名その二", "失敗させる行", "架空の題名その三 (2/30まで)"]},
    )

    messages = [record.getMessage() for record in caplog.records if record.name == "backend.api"]
    joined = "\n".join(messages)
    assert "架空の題名" not in joined
    assert "失敗させる行" not in joined
    assert "内部の詳細" not in joined
    assert "タスク解析: 1件（警告 0件）" in messages
    assert "一括解析: 3件（成功 2件・失敗 1件・警告あり 1件）" in messages


# ------------------------------------------------------------
# (6) CORS を外す（画面と API は同じオリジン）
# ------------------------------------------------------------

def test_cors_preflight_from_other_site_gets_no_allow_headers(client):
    response = client.options(
        "/api/parse",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_cors_simple_request_from_other_site_gets_no_allow_headers(client):
    response = client.post(
        "/api/parse",
        json={"text": "メモ"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_same_origin_page_can_still_call_api(client):
    # 画面は同じオリジンから配信され、そこから API を呼ぶ
    assert client.get("/").status_code == 200
    assert client.post("/api/parse-batch", json={"tasks": ["メモ"]}).status_code == 200


# ------------------------------------------------------------
# (7) /docs と /openapi.json は既定で無効。環境変数で有効にできる
# ------------------------------------------------------------

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_404_by_default(client, path):
    assert client.get(path).status_code == 404


def test_api_docs_can_be_enabled_by_env():
    code = textwrap.dedent(
        """
        import warnings
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
        from backend.api import app

        with TestClient(app) as client:
            print(client.get("/docs").status_code, client.get("/openapi.json").status_code)
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
    assert result.stdout.split() == ["200", "200"]


# ------------------------------------------------------------
# 画面側: 行ごとの結果と注意を表示し、題名を HTML として解釈させない
# ------------------------------------------------------------

def test_frontend_handles_per_row_results(client):
    html = client.get("/").text
    assert "task.ok === false" in html
    assert "task.warnings" in html
    assert "title.textContent = task.title" in html
    assert "${task.title}" not in html
