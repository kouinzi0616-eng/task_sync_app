"""backend/task_sync（カレンダー同期用の解析部品）の挙動を記録する。

基準日は引数 today で固定できるので、実行日に依存しない。
B26 で仕様を変えたところは「B26 仕様変更」と書き、旧の値を残している。
細かい期限の仕様は共通検算表（tests/fixtures/due_cases.json）で確かめる。
"""
from __future__ import annotations

import json
import logging
from datetime import date

import pytest

from backend.task_sync.date_rules import extract_due_part, parse_due_expression
from backend.task_sync.models import DueType, TaskCategory
from backend.task_sync.normalizer import classify_category
from backend.task_sync.parser import parse_line, parse_tasks, parse_text

TODAY = date(2026, 10, 1)


@pytest.mark.parametrize(
    ("raw", "due", "due_type"),
    [
        ("3/15まで", "2027-03-15", DueType.EXACT),
        ("3/15", "2027-03-15", DueType.EXACT),
        ("12/25まで", "2026-12-25", DueType.EXACT),
        ("9/1まで", "2026-09-01", DueType.EXACT),  # 猶予（62日）の内なので今年のまま・期限切れ
        ("7/31まで", "2026-07-31", DueType.EXACT),  # ちょうど62日前。今年のまま・期限切れ
        ("15日まで", "2026-10-15", DueType.EXACT),
        ("3月15日まで", "2027-03-15", DueType.EXACT),
        ("5月中", "2027-05-31", DueType.MONTH_END),
        ("10月まで", "2026-10-31", DueType.MONTH_END),
        # B26 仕様変更: 旧は 2027-09-30（過ぎた月は翌年）。直近の過去は今年のまま「期限切れ」にする
        ("9月中", "2026-09-30", DueType.MONTH_END),
        ("早め", "2026-10-04", DueType.SOON),
        ("なるべく早く", "2026-10-04", DueType.SOON),
        # B26 仕様変更: 旧は SOON の3日後（2026-10-04）。Web と同じ「至急 = 翌日」にそろえた
        ("至急", "2026-10-02", DueType.URGENT),
        ("ASAP", "2026-10-04", DueType.SOON),
        ("20日以降", "2026-10-20", DueType.AFTER),
        ("3/15以降", "2027-03-15", DueType.AFTER),
        # B26 仕様変更: 旧は解釈されず NONE・翌日。Web と同じ「来週の日曜」にそろえた
        ("来週まで", "2026-10-11", DueType.WEEK),
        # B26 仕様変更: 旧は NONE で翌日の日付を返した。解析は「期限なし（None）」を返し、
        # カレンダー用の「翌日」は parser.parse_line だけが付ける
        ("メモ", None, DueType.NONE),
    ],
)
def test_parse_due_expression(raw, due, due_type):
    result = parse_due_expression(raw, today=TODAY)
    assert (result.due_date.isoformat() if result.due_date else None) == due
    assert result.due_type == due_type
    assert result.raw_text == raw


@pytest.mark.parametrize(("raw", "overdue"), [("9/1まで", True), ("7/31まで", True), ("12/25まで", False)])
def test_recent_past_dates_are_overdue_and_need_review(raw, overdue):
    result = parse_due_expression(raw, today=TODAY)
    assert result.overdue is overdue
    assert result.needs_review is overdue


@pytest.mark.parametrize("raw", ["2/30まで", "13/1まで", "13月中"])
def test_nonexistent_dates_need_review_instead_of_raising(raw):
    # B26 仕様変更: 旧は ValueError で、parse_text がその行を黙って捨てていた
    result = parse_due_expression(raw, today=TODAY)
    assert result.due_date is None
    assert result.due_type == DueType.UNKNOWN
    assert result.needs_review is True
    assert "存在しない日付" in result.warnings[0]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("法要の準備（3/15まで）", ("法要の準備", "3/15まで")),
        ("法要の準備 (3/15まで) ", ("法要の準備", "3/15まで")),
        ("資料", ("資料", "")),
        ("(メモ)資料(早め)", ("(メモ)資料", "早め")),  # 行末の括弧だけを期限とみなす
    ],
)
def test_extract_due_part(line, expected):
    assert extract_due_part(line) == expected


def test_parse_line_strips_bullet_and_due_part():
    task = parse_line("・ 法要の準備（3/15まで）", today=TODAY)
    assert task is not None
    assert task.source_text == "・ 法要の準備（3/15まで）"
    assert task.title == "法要の準備"
    assert task.category == TaskCategory.TEMPLE
    assert task.due_date == date(2027, 3, 15)
    assert task.due_type == DueType.EXACT
    assert task.due_raw == "3/15まで"
    # task_id はカテゴリ・題名・期限日から作る安定した値
    assert task.task_id == parse_line("- 法要の準備 (3/15まで)", today=TODAY).task_id
    assert len(task.task_id) == 16


@pytest.mark.parametrize("line", ["", "   ", "# コメント", "・"])
def test_parse_line_skips_blank_comment_and_bullet_only(line):
    assert parse_line(line, today=TODAY) is None


def test_parse_text_returns_one_result_per_input_line():
    # B26 仕様変更: 旧は「資料A (2/30まで)」の行を黙って捨て、ログに行の文字を出していた
    text = "資料A (2/30まで)\n資料B (3/1まで)\n\n- 資料C\n# メモ\n(4/1まで)"
    results = parse_text(text, today=TODAY)
    assert len(results) == len(text.splitlines())  # 欠落0
    assert [result.line_no for result in results] == [1, 2, 3, 4, 5, 6]
    assert [result.status for result in results] == ["task", "task", "skipped", "task", "skipped", "task"]
    tasks = [result.task for result in results]
    assert tasks[0].title == "資料A"
    assert tasks[0].needs_review is True
    assert tasks[0].due_type == DueType.UNKNOWN
    assert tasks[0].due_date == date(2026, 10, 2)  # カレンダー用に翌日へ置く（要確認の印つき）
    assert tasks[1].title == "資料B" and tasks[1].needs_review is False
    assert tasks[3].title == "資料C" and tasks[3].due_type == DueType.NONE
    # 期限だけの行も捨てない（旧は題名が空なので None で消えていた）
    assert tasks[5].title == "(4/1まで)" and tasks[5].needs_review is True
    assert [result.needs_review for result in results] == [True, False, False, False, False, True]
    assert [task.title for task in parse_tasks(text, today=TODAY)] == ["資料A", "資料B", "資料C", "(4/1まで)"]


def test_parse_text_keeps_row_when_parse_line_raises(monkeypatch):
    import backend.task_sync.parser as parser_module

    def broken(line, today=None):
        raise RuntimeError("内部の詳細-0000")

    monkeypatch.setattr(parser_module, "parse_line", broken)
    results = parse_text("資料A\n資料B", today=TODAY)
    assert [result.status for result in results] == ["error", "error"]
    assert all(result.needs_review for result in results)
    assert results[0].reason == parser_module.ROW_ERROR_MESSAGE


def test_parse_text_logs_counts_but_not_line_text(caplog):
    caplog.set_level(logging.DEBUG, logger="task_sync")
    parse_text("架空の題名その一 (2/30まで)\n架空の題名その二 (3/1まで)\n", today=TODAY)
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "架空の題名" not in joined
    assert "2/30" not in joined
    assert "パース完了: 2行 → タスク2件（要確認1件・失敗0件・空行など0件）" in joined


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("寺の掃除", TaskCategory.TEMPLE),
        ("会報の発送", TaskCategory.SEIHOUKAI),
        ("和讃の練習", TaskCategory.EIDOUBU),
        ("買い物", TaskCategory.PERSONAL),
    ],
)
def test_classify_category(text, expected):
    assert classify_category(text) == expected


def test_description_text_contains_source_and_due():
    task = parse_line("法要の準備 (3/15まで)", today=TODAY)
    lines = task.description_text.splitlines()
    assert lines[0] == "【原文】法要の準備 (3/15まで)"
    assert lines[-1] == "【期限原文】3/15まで"


def test_json_lines_handler_writes_one_json_per_line(tmp_path):
    from backend.task_sync.logger import JsonLinesHandler

    handler = JsonLinesHandler(log_dir=tmp_path)
    try:
        logger = logging.getLogger("task_sync.test_json_lines")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.info("件数: %d", 3)
    finally:
        logger.removeHandler(handler)
        handler.close()

    lines = handler.filepath.read_text(encoding="utf-8").splitlines()
    assert handler.filepath.suffix == ".jsonl"
    assert [json.loads(line)["msg"] for line in lines] == ["件数: 3"]


def test_calendar_event_body_is_all_day_event():
    pytest.importorskip("googleapiclient", reason="requirements-calendar.txt が入っていない")
    from backend.task_sync.calendar_client import GoogleCalendarClient

    task = parse_line("法要の準備 (3/15まで)", today=TODAY)
    body = GoogleCalendarClient._build_event_body(task)
    assert body["start"] == {"date": "2027-03-15"}
    assert body["end"] == {"date": "2027-03-16"}
    assert body["extendedProperties"]["private"]["task_id"] == task.task_id
    assert body["summary"] == f"[{TaskCategory.TEMPLE.value}] 法要の準備"
