"""backend/task_sync（カレンダー同期用の解析部品）の今の挙動を記録する。

基準日は引数 today で固定できるので、実行日に依存しない。
"""
from __future__ import annotations

import json
import logging
from datetime import date

import pytest

from backend.task_sync.date_rules import extract_due_part, parse_due_expression
from backend.task_sync.models import DueType, TaskCategory
from backend.task_sync.normalizer import classify_category
from backend.task_sync.parser import parse_line, parse_text

TODAY = date(2026, 10, 1)


@pytest.mark.parametrize(
    ("raw", "due", "due_type"),
    [
        ("3/15まで", "2027-03-15", DueType.EXACT),
        ("3/15", "2027-03-15", DueType.EXACT),
        ("12/25まで", "2026-12-25", DueType.EXACT),
        ("9/1まで", "2026-09-01", DueType.EXACT),  # 約2か月前までは今年のまま
        ("7/31まで", "2026-07-31", DueType.EXACT),
        ("15日まで", "2026-10-15", DueType.EXACT),
        ("3月15日まで", "2027-03-15", DueType.EXACT),
        ("5月中", "2027-05-31", DueType.MONTH_END),
        ("10月まで", "2026-10-31", DueType.MONTH_END),
        ("9月中", "2027-09-30", DueType.MONTH_END),
        ("早め", "2026-10-04", DueType.SOON),
        ("なるべく早く", "2026-10-04", DueType.SOON),
        ("至急", "2026-10-04", DueType.SOON),
        ("ASAP", "2026-10-04", DueType.SOON),
        ("20日以降", "2026-10-20", DueType.AFTER),
        ("3/15以降", "2027-03-15", DueType.AFTER),
        # 「来週まで」は解釈されず、期限なし（翌日）扱い
        ("来週まで", "2026-10-02", DueType.NONE),
        ("メモ", "2026-10-02", DueType.NONE),
    ],
)
def test_parse_due_expression(raw, due, due_type):
    result = parse_due_expression(raw, today=TODAY)
    assert result.due_date.isoformat() == due
    assert result.due_type == due_type
    assert result.raw_text == raw


@pytest.mark.parametrize("raw", ["2/30まで", "13/1まで", "13月中"])
def test_parse_due_expression_raises_for_nonexistent_dates(raw):
    with pytest.raises(ValueError):
        parse_due_expression(raw, today=TODAY)


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


def test_parse_text_skips_lines_with_nonexistent_dates():
    tasks = parse_text("資料A (2/30まで)\n資料B (3/1まで)\n\n- 資料C", today=TODAY)
    assert [task.title for task in tasks] == ["資料B", "資料C"]


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
