"""B26: 解析 API の応答に足した項目（due_type・due_raw・due_time・needs_review・overdue）。

基準日は 2026-10-01（木）10:00 JST に固定。文字列はすべて架空。
既存の項目（title・deadline・category・raw_text・warnings、一括の ok・error）は変えない。
"""
from __future__ import annotations

import pytest

import backend.api as api

NEW_FIELDS = ("due_type", "due_raw", "due_time", "needs_review", "overdue")


def test_parse_returns_how_the_due_was_read(client, frozen_now):
    body = client.post("/api/parse", json={"text": "書類の提出 (3/15まで)"}).json()
    assert body["deadline"] == "2027-03-15T00:00:00+09:00"
    assert {key: body[key] for key in NEW_FIELDS} == {
        "due_type": "exact",
        "due_raw": "3/15まで",
        "due_time": None,
        "needs_review": False,
        "overdue": False,
    }


def test_parse_without_due_has_defaults(client, frozen_now):
    body = client.post("/api/parse", json={"text": "メモを書く"}).json()
    assert body["deadline"] is None
    assert {key: body[key] for key in NEW_FIELDS} == {
        "due_type": "none",
        "due_raw": "",
        "due_time": None,
        "needs_review": False,
        "overdue": False,
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 時刻は due_time に分けて返す。deadline は日付の 0:00 のまま
        (
            "会議資料の準備 (10/5 午後3時)",
            {"deadline": "2026-10-05T00:00:00+09:00", "due_type": "exact", "due_time": "15:00",
             "needs_review": False, "overdue": False},
        ),
        # 直近の過去日は今年のまま期限切れ・要確認
        (
            "名簿の整理 (9/30まで)",
            {"deadline": "2026-09-30T00:00:00+09:00", "due_type": "exact", "due_time": None,
             "needs_review": True, "overdue": True},
        ),
        # 読めない期限らしい括弧は、期限なし・要確認（題名に残す）
        (
            "書類の提出 (連休明け)",
            {"deadline": None, "due_type": "unknown", "due_time": None,
             "needs_review": True, "overdue": False},
        ),
        # 来週火曜（木曜に書いた）
        (
            "掃除当番の連絡 (来週火曜)",
            {"deadline": "2026-10-06T00:00:00+09:00", "due_type": "relative", "due_time": None,
             "needs_review": False, "overdue": False},
        ),
    ],
)
def test_parse_new_fields(client, frozen_now, text, expected):
    body = client.post("/api/parse", json={"text": text}).json()
    assert {key: body[key] for key in expected} == expected
    assert body["needs_review"] is bool(body["warnings"])


def test_unreadable_due_stays_in_title_with_warning(client, frozen_now):
    body = client.post("/api/parse", json={"text": "書類の提出 (連休明け)"}).json()
    assert body["title"] == "書類の提出 (連休明け)"
    assert body["due_raw"] == "連休明け"
    assert body["warnings"] and "読めませんでした" in body["warnings"][0]


def test_batch_rows_have_new_fields_and_failed_rows_need_review(client, frozen_now, monkeypatch):
    def classify_or_fail(text):
        if "失敗させる行" in text:
            raise RuntimeError("内部の詳細-0000")
        return api.Category.PERSONAL

    monkeypatch.setattr(api, "classify_category", classify_or_fail)
    response = client.post(
        "/api/parse-batch",
        json={"tasks": ["書類の提出 (至急)", "失敗させる行 (3/15まで)", "書類 (2/30まで)"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["ok"] for item in body] == [True, False, True]
    assert [item["due_type"] for item in body] == ["urgent", None, "unknown"]
    assert [item["needs_review"] for item in body] == [False, True, True]
    assert body[0]["due_raw"] == "至急"
    assert body[1]["error"] == api.ROW_ERROR_MESSAGE
    assert "内部の詳細" not in response.text


def test_sync_request_still_accepts_old_shape(client):
    # 画面が古いまま（新しい項目なし）で送っても受け付ける
    old_shape = {
        "title": "書類", "deadline": None, "category": api.Category.PERSONAL.value,
        "raw_text": "書類", "warnings": [],
    }
    response = client.post("/api/sync-calendar", json={"tasks": [old_shape]})
    assert response.status_code == 200
    assert response.json()["tasks_count"] == 1


def test_frontend_shows_reading_and_review_marks_with_text_content(client):
    html = client.get("/").text
    assert "task.needs_review" in html
    assert "task.overdue" in html
    assert "reading.textContent = `読み取り: 「${task.due_raw}」→ ${how}`" in html
    assert "review.textContent = '要確認'" in html
    # 入力に由来する文字（due_raw・title）を innerHTML に入れない
    for line in html.splitlines():
        if "innerHTML" in line:
            assert "task." not in line, line


def test_service_worker_cache_name_was_bumped_for_new_screen(client):
    # 画面を変えたらキャッシュ名の番号を上げる（古い画面が残らないように）
    assert "task-sync-v3" in client.get("/sw.js").text
