"""
============================================================
日付パーサー
============================================================
日本語の日付表現を解析してdatetimeオブジェクトに変換

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: python-dateutil
============================================================
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

# 日本時間のタイムゾーン（Windows では tzdata パッケージから読む）
JST = ZoneInfo('Asia/Tokyo')

# 数字は半角・全角のどちらでもよい
_NUM = r"[0-9０-９]{1,2}"

# 期限を書いた丸括弧（全角・半角のどちらでもよい）。
# 期限の取り出しと、題名からの除去は、この正規表現1か所で行う。
DUE_EXPRESSION_RE = re.compile(
    r"[(（]\s*(?:"
    rf"(?P<md_month>{_NUM})\s*[/／]\s*(?P<md_day>{_NUM})\s*まで"  # (3/15まで)
    rf"|(?P<month_only>{_NUM})\s*月中"  # (5月中)
    r"|(?P<soon>早め|はやめ)"  # (早め)
    r"|(?P<urgent>至急|しきゅう)"  # (至急)
    r"|(?P<next_week>来週まで|来週)"  # (来週まで) (来週)
    r")\s*[)）]"
)

# 1行に複数の期限があるときの優先順（前にあるほど優先）
_PRIORITY = ("md_month", "month_only", "soon", "urgent", "next_week")


@dataclass(frozen=True)
class DeadlineResult:
    """期限の解析結果"""
    deadline: Optional[datetime]  # 期限（JST の 0:00）。無い・読めないときは None
    title: str  # 期限の部分を除いた題名
    warnings: tuple[str, ...] = ()  # 利用者に見せる注意（例: 存在しない日付）


def _today_jst(now: Optional[datetime] = None) -> datetime:
    """基準日（JST の 0:00）を返す。now を渡すとそれを基準にする（テスト用）"""
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _pick(matches: list[re.Match[str]]) -> tuple[str, re.Match[str]]:
    """優先順が最も高い種類の、行の中で最初の期限を選ぶ"""
    for kind in _PRIORITY:
        for match in matches:
            if match.group(kind) is not None:
                return kind, match
    raise ValueError("期限の種類を判定できません")  # 正規表現の定義上ここには来ない


def _resolve(kind: str, match: re.Match[str], now: datetime) -> datetime:
    """期限の日時を求める。存在しない月日なら ValueError"""
    # パターン1: (3/15まで) → 月/日。過去の日付なら翌年と解釈
    if kind == "md_month":
        month = int(match.group("md_month"))
        day = int(match.group("md_day"))
        result = now.replace(year=now.year, month=month, day=day)
        if result < now:
            result = result.replace(year=now.year + 1)
        return result

    # パターン2: (5月中) → その月の末日。過去なら翌年
    if kind == "month_only":
        month = int(match.group("month_only"))
        if not 1 <= month <= 12:
            raise ValueError("month must be in 1..12")
        if month == 12:
            result = now.replace(month=12, day=31)
        else:
            # 翌月1日の前日 = その月の末日
            result = now.replace(month=month + 1, day=1) - timedelta(days=1)
        if result < now:
            result = result + relativedelta(years=1)
        return result

    # パターン3: (早め) → 3日後
    if kind == "soon":
        return now + timedelta(days=3)

    # パターン4: (至急) → 明日
    if kind == "urgent":
        return now + timedelta(days=1)

    # パターン5: (来週まで) → 来週日曜日
    # 今日の曜日（月曜=0, 日曜=6）から、次の日曜日までの日数を求める
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7  # 今日が日曜なら来週の日曜
    return now + timedelta(days=days_until_sunday + 7)


def parse_deadline(text: str, now: Optional[datetime] = None) -> DeadlineResult:
    """
    タスクの1行から期限を取り出し、期限の部分を除いた題名と一緒に返す

    対応パターン（括弧は全角・半角のどちらでもよい）:
    - (3/15まで) → 2026-03-15（過ぎていれば翌年）
    - (5月中) → 2026-05-31（過ぎていれば翌年）
    - (早め) → 3日後
    - (至急) → 明日
    - (来週まで) → 来週日曜日

    存在しない月日（2/30、平年の2/29、13/1、13月中 など）は例外にせず、
    「期限なし」と警告を返す。

    Args:
        text: 解析対象のテキスト
        now: 基準の日時（省略時は現在の JST）

    Returns:
        DeadlineResult: 期限（JST、時刻は00:00:00）・題名・警告
    """
    today = _today_jst(now)
    matches = list(DUE_EXPRESSION_RE.finditer(text))
    title = DUE_EXPRESSION_RE.sub("", text).strip()
    warnings: list[str] = []

    deadline: Optional[datetime] = None
    if matches:
        kind, match = _pick(matches)
        try:
            deadline = _resolve(kind, match, today)
        except ValueError:
            warnings.append(
                f"「{match.group(0).strip()}」は存在しない日付なので、期限なしにしました"
            )

    if not title and text.strip():
        # 期限だけの行は、元の文字をそのまま題名にする
        title = text.strip()
        warnings.append("題名がありません（期限だけが書かれています）")

    return DeadlineResult(deadline=deadline, title=title, warnings=tuple(warnings))


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
