"""共通検算表 tests/fixtures/due_cases.json の全件を確かめる（B26）。

- 期待値は仕様（README の「期限の書き方」）から手で書いたもの。文例はすべて架空。
- 同じ表を、解析の正本（date_rules）・Web API の互換層（date_parser）・
  task_sync の parse_line の3つの入口で確かめ、答えが食い違わないことを見る。
- 一本化の前の2つの系統（old_web・old_task_sync）と答えが違う行は、
  備考（note）に【旧と違う】と理由が書いてあることを確かめる。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from backend.date_parser import JST, parse_deadline
from backend.task_sync.date_rules import parse_due_in_line
from backend.task_sync.models import DueType
from backend.task_sync.parser import parse_line

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "due_cases.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = DATA["cases"]
KEYS = {
    "id", "today", "input", "expected_due", "expected_time", "expected_type",
    "needs_review", "expected_overdue", "note", "old_web", "old_task_sync",
}
MIN_CASES = 120


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _today(case: dict) -> date:
    return date.fromisoformat(case["today"])


def test_fixture_has_enough_well_formed_cases():
    assert len(CASES) >= MIN_CASES
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert len({(case["today"], case["input"]) for case in CASES}) == len(CASES)
    valid_types = {member.value for member in DueType}
    for case in CASES:
        assert set(case) == KEYS, case["id"]
        assert case["expected_type"] in valid_types, case["id"]
        assert case["note"], case["id"]
        if case["expected_due"] is None:
            assert case["expected_time"] is None, case["id"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_due_case(case):
    result = parse_due_in_line(case["input"], today=_today(case))
    actual = {
        "due": _iso(result.due_date),
        "time": result.due_time.strftime("%H:%M") if result.due_time else None,
        "type": result.due_type.value,
        "needs_review": result.needs_review,
        "overdue": result.overdue,
    }
    expected = {
        "due": case["expected_due"],
        "time": case["expected_time"],
        "type": case["expected_type"],
        "needs_review": case["needs_review"],
        "overdue": case["expected_overdue"],
    }
    assert actual == expected, f"{case['input']} / {case['note']} / {result.warnings}"
    # 要確認の印は、理由（warnings）があるときだけ付く
    assert result.needs_review is bool(result.warnings)


def test_web_api_path_agrees_with_fixture():
    """Web API が使う互換層（date_parser）でも、全件が同じ答えになる。"""
    mismatches = []
    for case in CASES:
        now = datetime.fromisoformat(case["today"]).replace(hour=10, tzinfo=JST)
        result = parse_deadline(case["input"], now=now)
        got = (
            result.deadline.date().isoformat() if result.deadline else None,
            result.due_time,
            result.due_type,
            result.needs_review,
            result.overdue,
        )
        want = (
            case["expected_due"],
            case["expected_time"],
            case["expected_type"],
            case["needs_review"],
            case["expected_overdue"],
        )
        if got != want:
            mismatches.append((case["id"], got, want))
        if result.deadline:
            assert (result.deadline.hour, result.deadline.minute) == (0, 0)
            assert result.deadline.utcoffset() == timedelta(hours=9)
    assert mismatches == []


def test_task_sync_path_agrees_with_fixture():
    """task_sync の parse_line でも、期限・種類・要確認が同じ。期限なしだけはカレンダー用に翌日へ置く。"""
    mismatches = []
    for case in CASES:
        today = _today(case)
        task = parse_line(case["input"], today=today)
        assert task is not None, case["id"]  # 行を捨てない
        want_due = case["expected_due"] or (today + timedelta(days=1)).isoformat()
        got = (task.due_date.isoformat(), task.due_type.value, task.needs_review)
        want = (want_due, case["expected_type"], case["needs_review"])
        if got != want:
            mismatches.append((case["id"], got, want))
    assert mismatches == []


def test_changes_from_old_parsers_are_documented_in_notes():
    """一本化の前と答えが違う行は、備考に【旧と違う】と、どちらの系統と違うかが書いてある。"""
    for case in CASES:
        today = _today(case)
        new_task_sync = case["expected_due"] or (today + timedelta(days=1)).isoformat()
        web_changed = case["old_web"] != case["expected_due"]
        task_sync_changed = case["old_task_sync"] != new_task_sync
        note = case["note"]
        assert ("旧Web:" in note) is web_changed, case["id"]
        assert ("旧task_sync:" in note) is task_sync_changed, case["id"]
        assert ("【旧と違う】" in note) is (web_changed or task_sync_changed), case["id"]


def test_fixture_covers_the_required_situations():
    """仕様に挙げた場面（来週火曜を日曜・月曜に書く、年またぎ、祝日、時刻など）が入っている。"""
    def has(predicate) -> bool:
        return any(predicate(case) for case in CASES)

    def weekday(case) -> int:
        return _today(case).weekday()

    assert has(lambda c: "来週火曜" in c["input"] and weekday(c) == 6)  # 日曜に言った
    assert has(lambda c: "来週火曜" in c["input"] and weekday(c) == 0)  # 月曜に言った
    assert has(lambda c: "再来週" in c["input"])
    assert has(lambda c: "月末" in c["input"])
    assert has(lambda c: c["expected_due"] and c["expected_due"][:4] > c["today"][:4])  # 年またぎ
    assert has(lambda c: "祝" in c["input"] or "祝日" in c["note"])
    assert has(lambda c: "午前" in c["input"]) and has(lambda c: "午後" in c["input"])
    assert has(lambda c: "時半" in c["input"])
    assert has(lambda c: c["expected_due"] and c["expected_time"] is None)  # 時刻なし
    assert has(lambda c: "終日" in c["input"])
    assert has(lambda c: "2つ" in c["note"])  # 複数の日時
    assert has(lambda c: "あいまい" in c["note"])
    assert has(lambda c: c["expected_overdue"])  # 過去日
    assert has(lambda c: "令和" in c["input"])  # 和暦
    assert has(lambda c: "2/29" in c["input"])
    for word in ("上旬", "中旬", "下旬", "今週中", "年度末", "日まで"):
        assert has(lambda c, word=word: word in c["input"]), word
