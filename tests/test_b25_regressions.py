"""B25（解析 API の即時修正）の回帰テスト。

基準日は 2026-10-01（木）JST に固定。文字列はすべて架空。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.date_parser import JST, parse_date, parse_deadline
from backend.models import Category

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=JST)


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


def test_feb_29_after_it_passed_in_leap_year_warns_instead_of_crashing():
    # 2028-02-29 は過ぎているので翌年にしたいが、2029-02-29 は存在しない
    result = parse_deadline("資料 (2/29まで)", now=datetime(2028, 3, 5, tzinfo=JST))
    assert result.deadline is None
    assert result.warnings


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
