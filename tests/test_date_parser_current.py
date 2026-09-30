"""backend/date_parser.py（Web API が使う期限解析）の今の挙動を記録する。

基準日は conftest の frozen_now（2026-10-01 木曜 10:00 JST）に固定している。
期限解析の一本化（B26）で挙動を変えるときは、このテストも合わせて直す。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.date_parser import parse_date


def iso(text: str) -> str | None:
    result = parse_date(text)
    return result.isoformat() if result else None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # (M/Dまで): 今年の日付。過ぎていれば翌年
        ("資料作り (12/25まで)", "2026-12-25T00:00:00+09:00"),
        ("資料作り (3/15まで)", "2027-03-15T00:00:00+09:00"),
        ("資料作り (10/1まで)", "2026-10-01T00:00:00+09:00"),  # 当日は今年のまま
        ("資料作り (9/30まで)", "2027-09-30T00:00:00+09:00"),  # 前日は翌年
        # (M月中): その月の末日。過ぎていれば翌年
        ("資料作り (10月中)", "2026-10-31T00:00:00+09:00"),
        ("資料作り (12月中)", "2026-12-31T00:00:00+09:00"),
        ("資料作り (5月中)", "2027-05-31T00:00:00+09:00"),
        ("資料作り (2月中)", "2027-02-28T00:00:00+09:00"),
        # (早め) は3日後、(至急) は翌日
        ("資料作り (早め)", "2026-10-04T00:00:00+09:00"),
        ("資料作り (はやめ)", "2026-10-04T00:00:00+09:00"),
        ("資料作り (至急)", "2026-10-02T00:00:00+09:00"),
        ("資料作り (しきゅう)", "2026-10-02T00:00:00+09:00"),
        # (来週まで) (来週) は「来週の日曜」
        ("資料作り (来週まで)", "2026-10-11T00:00:00+09:00"),
        ("資料作り (来週)", "2026-10-11T00:00:00+09:00"),
        # 期限の書き方が無ければ None
        ("資料作り", None),
        ("資料作り (メモ)", None),
    ],
)
def test_parse_date_current_behavior(frozen_now, text, expected):
    assert iso(text) == expected


def test_slash_date_has_priority_over_other_patterns(frozen_now):
    # 1行に複数あるときは (M/Dまで) が優先される
    assert iso("資料作り (至急)(3/15まで)") == "2027-03-15T00:00:00+09:00"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (datetime(2026, 10, 3, 9, 0), "2026-10-11"),  # 土曜 → 8日後の日曜
        (datetime(2026, 10, 4, 9, 0), "2026-10-18"),  # 日曜 → 14日後の日曜
        (datetime(2026, 10, 5, 9, 0), "2026-10-18"),  # 月曜 → 13日後の日曜
    ],
)
def test_next_week_is_sunday_after_this_week(freeze_jst, today, expected):
    # 今の実装は「今週の日曜の、さらに7日後」。日曜に入力すると2週間後になる（B26 で見直す候補）
    freeze_jst(today)
    result = parse_date("資料作り (来週まで)")
    assert result.date().isoformat() == expected
    assert result.weekday() == 6


def test_result_is_midnight_jst(frozen_now):
    result = parse_date("資料作り (早め)")
    assert (result.hour, result.minute, result.second) == (0, 0, 0)
    assert result.utcoffset().total_seconds() == 9 * 3600


def test_two_parsers_disagree_on_recent_past_dates(frozen_now):
    """Web API 用と task_sync 用で、少し前の日付の年の決め方が違う（B26 で一本化する）。"""
    from backend.task_sync.date_rules import parse_due_expression

    web = parse_date("資料作り (9/1まで)")
    cli = parse_due_expression("9/1まで", today=frozen_now.date())
    assert web.date().isoformat() == "2027-09-01"  # 過ぎていれば翌年
    assert cli.due_date.isoformat() == "2026-09-01"  # 約2か月前までは今年のまま
