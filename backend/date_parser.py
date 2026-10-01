"""
============================================================
日付パーサー
============================================================
日本語の日付表現を解析してdatetimeオブジェクトに変換

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: なし（標準ライブラリ。解析の本体は backend/task_sync/date_rules.py）
============================================================
"""
# ------------------------------------------------------------
# B26（2026-10）: 薄い互換層
# ------------------------------------------------------------
# 期限の読み方の正本は backend/task_sync/date_rules.py。ここは Web API 向けに
#   - 基準日を日本時間（JST）の「今日」にする
#   - 期限日を JST の 0:00 の datetime にする（応答の deadline の形を変えない）
# だけを行う。仕様は README.md の「期限の書き方」を見る。
# ------------------------------------------------------------
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from backend.task_sync.date_rules import parse_due_in_line

# 日本時間のタイムゾーン（Windows では tzdata パッケージから読む）
JST = ZoneInfo('Asia/Tokyo')


@dataclass(frozen=True)
class DeadlineResult:
    """期限の解析結果"""
    deadline: Optional[datetime]  # 期限（JST の 0:00）。無い・読めないときは None
    title: str  # 期限の部分を除いた題名
    warnings: tuple[str, ...] = ()  # 利用者に見せる注意（例: 存在しない日付）
    due_type: str = "none"  # 期限の種類（DueType の値: exact・month_end・week など）
    due_raw: str = ""  # 読み取った括弧の中身（例: "3/15まで"）
    due_time: Optional[str] = None  # 時刻 "HH:MM"（書いてあれば）
    needs_review: bool = False  # 人が確かめるべきか（warnings が1つでもあれば True）
    overdue: bool = False  # 期限を過ぎているか


def _today_jst(now: Optional[datetime] = None) -> datetime:
    """基準日（JST の 0:00）を返す。now を渡すとそれを基準にする（テスト用）"""
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_deadline(text: str, now: Optional[datetime] = None) -> DeadlineResult:
    """
    タスクの1行から期限を取り出し、期限の部分を除いた題名と一緒に返す

    中身は backend.task_sync.date_rules.parse_due_in_line。
    存在しない月日（2/30、平年の2/29、13/1、13月中 など）は例外にせず、
    「期限なし」と警告を返す。

    Args:
        text: 解析対象のテキスト
        now: 基準の日時（省略時は現在の JST）

    Returns:
        DeadlineResult: 期限（JST、時刻は00:00:00）・題名・警告・種類・原文・要確認
    """
    today = _today_jst(now)
    result = parse_due_in_line(text, today=today.date())

    deadline: Optional[datetime] = None
    if result.due_date is not None:
        deadline = today.replace(
            year=result.due_date.year, month=result.due_date.month, day=result.due_date.day,
        )

    return DeadlineResult(
        deadline=deadline,
        title=result.title,
        warnings=result.warnings,
        due_type=result.due_type.value,
        due_raw=result.due_raw,
        due_time=result.due_time.strftime("%H:%M") if result.due_time else None,
        needs_review=result.needs_review,
        overdue=result.overdue,
    )


def parse_date(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """
    日本語の日付表現を解析（期限だけが要るとき用。中身は parse_deadline）

    Args:
        text: 解析対象のテキスト
        now: 基準の日時（省略時は現在の JST）

    Returns:
        datetime | None: 解析された日付（JST、時刻は00:00:00）。無い・存在しない日付なら None
    """
    return parse_deadline(text, now=now).deadline
