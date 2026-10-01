"""backend/date_parser.py（Web API が使う期限解析）の挙動を記録する。

基準日は conftest の frozen_now（2026-10-01 木曜 10:00 JST）に固定している。
B26 で解析の本体を backend/task_sync/date_rules.py に一本化した。
仕様を変えた箇所は「B26 仕様変更」と書き、旧の値を残している。
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
        # B26 仕様変更: 旧は「前日は翌年」で 2027-09-30。直近の過去日は今年のまま「期限切れ」
        ("資料作り (9/30まで)", "2026-09-30T00:00:00+09:00"),
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


def test_two_due_parts_pick_the_earliest_and_need_review(frozen_now):
    # B26 仕様変更: 旧は (M/Dまで) を優先して 2027-03-15。
    # 期限が2つ以上なら、見落とさないよう「いちばん早い日」を採り、要確認にする
    from backend.date_parser import parse_deadline

    result = parse_deadline("資料作り (至急)(3/15まで)")
    assert result.deadline.isoformat() == "2026-10-02T00:00:00+09:00"
    assert result.title == "資料作り"
    assert result.needs_review is True
    assert any("2つ以上" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("today", "expected", "needs_review"),
    [
        (datetime(2026, 10, 3, 9, 0), "2026-10-11", False),  # 土曜 → 8日後の日曜
        # B26 仕様変更: 旧は 2026-10-18（日曜に入力すると2週間後）。週は月曜始まりなので、
        # 日曜の「来週」は翌日の月曜からの週 → 7日後の日曜。日曜始まりの人と食い違うので要確認
        (datetime(2026, 10, 4, 9, 0), "2026-10-11", True),
        (datetime(2026, 10, 5, 9, 0), "2026-10-18", False),  # 月曜 → 13日後の日曜
    ],
)
def test_next_week_is_sunday_of_next_monday_start_week(freeze_jst, today, expected, needs_review):
    from backend.date_parser import parse_deadline

    freeze_jst(today)
    result = parse_deadline("資料作り (来週まで)")
    assert result.deadline.date().isoformat() == expected
    assert result.deadline.weekday() == 6
    assert result.needs_review is needs_review


def test_result_is_midnight_jst(frozen_now):
    result = parse_date("資料作り (早め)")
    assert (result.hour, result.minute, result.second) == (0, 0, 0)
    assert result.utcoffset().total_seconds() == 9 * 3600


def test_two_parsers_now_agree_on_recent_past_dates(frozen_now):
    """B26 仕様変更: 旧は Web が 2027-09-01（過ぎていれば翌年）、task_sync が 2026-09-01 で食い違った。
    一本化して、どちらも「今年のまま・期限切れ・要確認」になる。"""
    from backend.date_parser import parse_deadline
    from backend.task_sync.date_rules import parse_due_expression

    web = parse_deadline("資料作り (9/1まで)")
    cli = parse_due_expression("9/1まで", today=frozen_now.date())
    assert web.deadline.date().isoformat() == "2026-09-01"
    assert cli.due_date.isoformat() == "2026-09-01"
    assert web.overdue is cli.overdue is True
    assert web.needs_review is cli.needs_review is True


def test_month_end_rollover_into_leap_year_uses_29th(freeze_jst):
    # B26 仕様変更: 旧は「今年の月末 + 1年」で、翌年がうるう年でも 2028-02-28 だった。
    # 翌年に繰り越すときは、その年の月末で数える
    freeze_jst(datetime(2027, 6, 1, 9, 0))
    assert parse_date("資料作り (2月中)").date().isoformat() == "2028-02-29"


def test_month_end_just_passed_is_overdue_this_year(freeze_jst):
    # B26 仕様変更: 旧（基準日 2027-03-01）は 2028-02-28。直近の過去なので今年のまま期限切れ
    from backend.date_parser import parse_deadline

    freeze_jst(datetime(2027, 3, 1, 9, 0))
    result = parse_deadline("資料作り (2月中)")
    assert result.deadline.date().isoformat() == "2027-02-28"
    assert result.overdue is True
