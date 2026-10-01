"""
============================================================
date_rules.py — 日本語期限表現の解釈エンジン
============================================================
「(3/15まで)」「(5月中)」「(早め)」等の自然文を
datetime.date に変換するルールベースパーサー。

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
============================================================
"""

# ------------------------------------------------------------
# B26（2026-10）: 期限解析の正本
# ------------------------------------------------------------
# - Web API（backend/date_parser.py は薄い互換層）と task_sync の両方がここを使う。
# - 基準日 today は必ず引数で渡せる（省略時だけ実行日）。日付を固定した試験ができる。
# - 仕様は README.md の「期限の書き方」と、共通検算表 tests/fixtures/due_cases.json にある。
# - 祝日の判定はしない。外部の API も使わない（標準ライブラリだけ）。
# - 読めない・あいまいなものは捨てずに「要確認（needs_review）」と理由（warnings）を返す。
# ------------------------------------------------------------

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Callable, Optional

from .models import DueType

# ═══════════════════════════════════════════════════════════════
# 定数（マジックナンバー禁止）
# ═══════════════════════════════════════════════════════════════

# 「早め」「なるべく早め」の場合、今日から何日後をデフォルト期限とするか
SOON_OFFSET_DAYS = 3

# 「至急」は翌日、「大至急」は今日
URGENT_OFFSET_DAYS = 1
VERY_URGENT_OFFSET_DAYS = 0

# 期限指定なしの場合、今日から何日後をデフォルト期限とするか。
# 解析エンジン自体は「期限なし（None）」を返す。カレンダーに置く日が要る task_sync の
# parser だけがこの値を使う。
NO_DEADLINE_OFFSET_DAYS = 1

# 年を書かない日付（3/15・5月中・10月上旬）が過ぎていたとき、何日前までなら
# 「今年のまま・期限切れ」にするか。これより前なら翌年の日付と読む。
PAST_DUE_GRACE_DAYS = 62

# 上旬・中旬は、その月の何日にするか（下旬は末日）
EARLY_PART_DAY = 10
MIDDLE_PART_DAY = 20

# 年度末（日本の会計年度: 4月始まり・3月終わり）
FISCAL_YEAR_END_MONTH = 3

# 曜日（date.weekday() の番号順。週は月曜始まり）
WEEKDAY_NAMES = "月火水木金土日"

# 和暦の元年の前の年（令和1年 = 2019年）
ERA_BASE_YEARS = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925}

# 時刻: 午前・午後の無い 1〜6時は、午後（13〜18時）と読む
AFTERNOON_GUESS_MAX_HOUR = 6


# ═══════════════════════════════════════════════════════════════
# 解釈結果
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DateParseResult:
    """括弧の中身1つ分の解釈結果"""
    due_date: Optional[date]  # 期限日。期限なし・読めないときは None
    due_type: DueType
    raw_text: str  # 括弧内の原文
    due_time: Optional[time] = None  # 時刻（書いてあれば）
    needs_review: bool = False  # 人が確かめるべきか（warnings が1つでもあれば True）
    overdue: bool = False  # 期限を過ぎているか
    warnings: tuple[str, ...] = ()  # 要確認の理由（利用者に見せる文）
    recognized: bool = False  # 期限の形として読めたか（存在しない日付も含む）。False なら題名に残す


@dataclass(frozen=True)
class LineDueResult:
    """タスク1行分の解釈結果（期限の括弧を除いた題名つき）"""
    title: str
    due_date: Optional[date]
    due_type: DueType
    due_raw: str  # 読み取った括弧の中身（無ければ ""）
    due_time: Optional[time] = None
    needs_review: bool = False
    overdue: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Atom:
    """括弧の中で見つかった日付の部品1つ"""
    text: str
    due: Optional[date]  # None なら存在しない日付
    due_type: DueType
    notes: tuple[str, ...] = ()  # 要確認の理由
    week_based: bool = False  # 今週・来週など「週」で数えたもの


# ═══════════════════════════════════════════════════════════════
# 小さな道具
# ═══════════════════════════════════════════════════════════════

def _normalize(text: str) -> str:
    """全角の数字・括弧・斜線・英字を半角にそろえる（NFKC）"""
    return unicodedata.normalize("NFKC", text).strip()


def _month_len(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _shift_month(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    """存在しない日付なら None"""
    if not 1 <= month <= 12 or not 1 <= day <= _month_len(year, month):
        return None
    return date(year, month, day)


def _md(value: date) -> str:
    return f"{value.month}/{value.day}"


def _ymd(value: date) -> str:
    return f"{value.year}/{value.month}/{value.day}"


def _monday(today: date) -> date:
    """今週の月曜日（週は月曜始まり）"""
    return today - timedelta(days=today.weekday())


_PART_KIND = {"上旬": "early", "初旬": "early", "中旬": "middle", "下旬": "late"}


def _part_of(word: Optional[str]) -> str:
    """上旬・中旬・下旬なら early/middle/late、それ以外（末・中・まで・なし）は end"""
    return _PART_KIND.get(word or "", "end")


def _part_day(year: int, month: int, part: str) -> int:
    if part == "early":
        return EARLY_PART_DAY
    if part == "middle":
        return MIDDLE_PART_DAY
    return _month_len(year, month)


def _part_type(part: str) -> DueType:
    return DueType.MONTH_END if part == "end" else DueType.PERIOD


def _resolve_month_day(month: int, day: int, today: date) -> Optional[date]:
    """年の無い月日。今日以降なら今年。過ぎていれば猶予の日数までは今年（期限切れ）、それより前なら翌年"""
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    if (month, day) >= (today.month, today.day):
        year = today.year
    else:
        reference = date(today.year, month, min(day, _month_len(today.year, month)))
        within_grace = (today - reference).days <= PAST_DUE_GRACE_DAYS
        year = today.year if within_grace else today.year + 1
    return _safe_date(year, month, day)


def _resolve_month_part(month: int, part: str, today: date) -> Optional[date]:
    """年の無い「M月中・M月上旬」など。年の決め方は _resolve_month_day と同じ"""
    if not 1 <= month <= 12:
        return None
    this_year = date(today.year, month, _part_day(today.year, month, part))
    if this_year >= today or (today - this_year).days <= PAST_DUE_GRACE_DAYS:
        return this_year
    year = today.year + 1
    return date(year, month, _part_day(year, month, part))


# ═══════════════════════════════════════════════════════════════
# 正規表現（括弧の中身を NFKC で半角にそろえてから使う）
# ═══════════════════════════════════════════════════════════════

# 日付の後ろの曜日の注記: 10/5(月)  10/5(月・祝)  11/3(祝)
_WEEKDAY_NOTE_RE = re.compile(
    r"\(\s*(?P<wd>[月火水木金土日])\s*(?:曜日?)?\s*(?:[・,、]?\s*祝)?\s*\)|\(\s*祝\s*\)"
)

# 時刻: 15時 / 10時半 / 9時30分 / 午後3時 / 15:00 / 正午
_TIME_RE = re.compile(
    r"(?P<ampm>午前|午後|AM|PM)?\s*(?<![\d/:])(?P<h>\d{1,2})\s*"
    r"(?:時(?!間)\s*(?:(?P<half>半)|(?P<min>\d{1,2})\s*分)?|:\s*(?P<min2>\d{2})(?!\d))",
    re.IGNORECASE,
)
_NOON_RE = re.compile(r"正午")

# 月の中の位置（無ければ月末）
_MONTH_PART = r"\s*(?P<part>上旬|初旬|中旬|下旬|末|中|いっぱい|まで|迄)?"

# 年・和暦つきの日付
_ERA_FULL_RE = re.compile(
    r"(?P<era>令和|平成|昭和)\s*(?P<ey>元|\d{1,2})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日?"
)
_ERA_LETTER_RE = re.compile(
    r"(?<![A-Za-z])(?P<era>[RH])\s*(?P<ey>\d{1,2})\s*[./]\s*(?P<m>\d{1,2})\s*[./]\s*(?P<d>\d{1,2})(?!\d)"
)
_ERA_MONTH_RE = re.compile(
    r"(?P<era>令和|平成|昭和)\s*(?P<ey>元|\d{1,2})\s*年\s*(?P<m>\d{1,2})\s*月" + _MONTH_PART
)
_YEAR_FULL_RE = re.compile(
    r"(?<!\d)(?P<y>\d{4})\s*(?:年|[/.\-])\s*(?P<m>\d{1,2})\s*(?:月|[/.\-])\s*(?P<d>\d{1,2})(?!\d)\s*日?"
)
_YEAR_MONTH_RE = re.compile(r"(?<!\d)(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月" + _MONTH_PART)

# 年の無い日付
_SLASH_RE = re.compile(
    r"(?<![\d/])(?P<m>\d{1,2})\s*/\s*(?P<d>\d{1,2})(?![\d/])"
    r"(?!\s*(?:ページ|頁|枚|部|個|人|本|回|件|冊|号|P\b|p\b))"
)
_MONTH_DAY_RE = re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日")
_MONTH_RE = re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*月(?!\d)" + _MONTH_PART)
_AFTER_N_RE = re.compile(r"(?<!\d)(?P<n>\d{1,3})\s*(?P<unit>日|週間)\s*(?:後|以内|のうちに)")
_DAY_RE = re.compile(r"(?<![\d/第])(?P<d>\d{1,2})\s*日(?![\d分間目前後])")

# 週（月曜始まり）・曜日
_WEEK_OFFSET = {"今週": 0, "来週": 1, "翌週": 1, "再来週": 2}
_WEEK_DAY_RE = re.compile(r"(?P<week>再来週|来週|翌週|今週)\s*の?\s*(?P<wd>[月火水木金土日])\s*曜日?")
_WEEK_RE = re.compile(r"(?P<week>再来週|来週|翌週|今週)\s*(?P<suffix>末|中|いっぱい|まで|迄)?")
_WEEKEND_RE = re.compile(r"週末")
_WEEKDAY_RE = re.compile(r"(?P<wd>[月火水木金土日])\s*曜日?")

# 今月・来月・月末・上旬など
_REL_MONTH_OFFSET = {"今月": 0, "来月": 1, "再来月": 2}
_REL_MONTH_DAY_RE = re.compile(r"(?P<rel>再来月|来月|今月)\s*の?\s*(?P<d>\d{1,2})\s*日")
_REL_MONTH_RE = re.compile(r"(?P<rel>再来月|来月|今月)\s*の?" + _MONTH_PART)
_MONTH_END_RE = re.compile(r"月末|月内")
_BARE_PART_RE = re.compile(r"(?P<part>上旬|初旬|中旬|下旬)")
_YEAR_WORD_RE = re.compile(
    r"(?P<fy>今年度中|今年度内|今年度末|年度内|年度末|年度中)|(?P<cy>今年中|今年いっぱい|年内|年末)"
)

# 至急・今日・明日・早め
_URGENT_RE = re.compile(r"(?P<very>大至急)|至急|しきゅう|大急ぎ|急ぎ|いそぎ|早急|緊急")
_REL_DAY_RE = re.compile(
    r"(?P<d3>明々後日|明明後日|しあさって)|(?P<d2>明後日|あさって)"
    r"|(?P<d1>明日(?!葉)|あした|明朝|明晩)|(?P<d0>今日|本日|きょう|今夜|今晩)"
)
_SOON_RE = re.compile(
    r"なるはや|(?:なるべく|できるだけ|できる限り|一日も|一刻も)?(?:早|はや)[くめ]|ASAP",
    re.IGNORECASE,
)

# 期限の形が無いときに「期限らしいが読めない」と判断する手がかり
_DUE_HINT_RE = re.compile(
    r"まで|迄|以降|以内|明け|期限|締切|締め切り|〆|頃|ごろ|祝|休み|曜|週|旬|月中|月末|年内|年度"
    r"|の日|元日|元旦|正月|連休|急"
)
# 日付は読めたが、あいまいさが残る書き方
_UNSURE_RE = re.compile(
    r"頃|ごろ|くらい|ぐらい|未定|目安|かも|\?|たぶん|多分|あたり|前後|毎|次第|前日|の前|より前|頭|初め|はじめ"
)
_RANGE_RE = re.compile(r"[〜~]|から")
_AFTER_RE = re.compile(r"以降|以後|から")


# ═══════════════════════════════════════════════════════════════
# 部品ごとの読み方
# ═══════════════════════════════════════════════════════════════

def _era_year(era: str, era_year: str) -> int:
    return ERA_BASE_YEARS[era] + (1 if era_year == "元" else int(era_year))


def _year_of(match: re.Match[str]) -> int:
    groups = match.groupdict()
    if groups.get("y"):
        return int(groups["y"])
    return _era_year(groups["era"], groups["ey"])


def _atom_full_date(match: re.Match[str], today: date) -> _Atom:
    due = _safe_date(_year_of(match), int(match["m"]), int(match["d"]))
    return _Atom(match.group(0), due, DueType.EXACT)


def _atom_year_month(match: re.Match[str], today: date) -> _Atom:
    year = _year_of(match)
    month = int(match["m"])
    part = _part_of(match["part"])
    if not 1 <= month <= 12:
        return _Atom(match.group(0), None, _part_type(part))
    due = date(year, month, _part_day(year, month, part))
    notes = () if match["part"] else (f"「{month}月」だけなので、月末の{_md(due)}にしました",)
    return _Atom(match.group(0), due, _part_type(part), notes)


def _atom_month_day(match: re.Match[str], today: date) -> _Atom:
    due = _resolve_month_day(int(match["m"]), int(match["d"]), today)
    return _Atom(match.group(0), due, DueType.EXACT)


def _atom_month(match: re.Match[str], today: date) -> _Atom:
    month = int(match["m"])
    part = _part_of(match["part"])
    due = _resolve_month_part(month, part, today)
    notes: tuple[str, ...] = ()
    if due is not None and not match["part"]:
        notes = (f"「{month}月」だけなので、月末の{_md(due)}にしました",)
    return _Atom(match.group(0), due, _part_type(part), notes)


def _atom_after_n(match: re.Match[str], today: date) -> _Atom:
    days = int(match["n"]) * (7 if match["unit"] == "週間" else 1)
    return _Atom(match.group(0), today + timedelta(days=days), DueType.RELATIVE)


def _atom_day(match: re.Match[str], today: date) -> _Atom:
    """日だけ（5日まで）。今日以降なら今月、過ぎていれば翌月"""
    day = int(match["d"])
    if not 1 <= day <= 31:
        return _Atom(match.group(0), None, DueType.EXACT)
    if day >= today.day:
        year, month = today.year, today.month
    else:
        year, month = _shift_month(today.year, today.month, 1)
    last = _month_len(year, month)
    if day > last:
        due = date(year, month, last)
        note = f"{month}月に{day}日は無いので、末日の{_md(due)}にしました"
        return _Atom(match.group(0), due, DueType.EXACT, (note,))
    return _Atom(match.group(0), date(year, month, day), DueType.EXACT)


def _atom_week_day(match: re.Match[str], today: date) -> _Atom:
    weekday = WEEKDAY_NAMES.index(match["wd"])
    due = _monday(today) + timedelta(weeks=_WEEK_OFFSET[match["week"]], days=weekday)
    return _Atom(match.group(0), due, DueType.RELATIVE, week_based=True)


def _atom_week(match: re.Match[str], today: date) -> _Atom:
    """今週・来週・再来週 → その週の日曜日"""
    due = _monday(today) + timedelta(weeks=_WEEK_OFFSET[match["week"]], days=6)
    notes: tuple[str, ...] = ()
    if match["suffix"] == "末":
        notes = (f"「週末」は土曜とも日曜とも読めるので、日曜の{_md(due)}にしました",)
    return _Atom(match.group(0), due, DueType.WEEK, notes, week_based=True)


def _atom_weekend(match: re.Match[str], today: date) -> _Atom:
    due = _monday(today) + timedelta(days=6)
    note = f"「週末」は土曜とも日曜とも読めるので、日曜の{_md(due)}にしました"
    return _Atom(match.group(0), due, DueType.WEEK, (note,), week_based=True)


def _atom_weekday(match: re.Match[str], today: date) -> _Atom:
    """曜日だけ（金曜まで）→ 今日から数えて次のその曜日（今日が同じ曜日なら今日）"""
    name = match["wd"]
    delta = (WEEKDAY_NAMES.index(name) - today.weekday()) % 7
    notes: tuple[str, ...] = ()
    if delta == 0:
        notes = (f"今日が{name}曜日なので今日にしました（来週なら「来週{name}曜」と書いてください）",)
    return _Atom(match.group(0), today + timedelta(days=delta), DueType.RELATIVE, notes)


def _atom_rel_month_day(match: re.Match[str], today: date) -> _Atom:
    year, month = _shift_month(today.year, today.month, _REL_MONTH_OFFSET[match["rel"]])
    return _Atom(match.group(0), _safe_date(year, month, int(match["d"])), DueType.EXACT)


def _atom_rel_month(match: re.Match[str], today: date) -> _Atom:
    year, month = _shift_month(today.year, today.month, _REL_MONTH_OFFSET[match["rel"]])
    part = _part_of(match["part"])
    return _Atom(match.group(0), date(year, month, _part_day(year, month, part)), _part_type(part))


def _atom_month_end(match: re.Match[str], today: date) -> _Atom:
    due = date(today.year, today.month, _month_len(today.year, today.month))
    return _Atom(match.group(0), due, DueType.MONTH_END)


def _atom_bare_part(match: re.Match[str], today: date) -> _Atom:
    """月の無い上旬・中旬・下旬 → 今月。過ぎていれば翌月"""
    part = _PART_KIND[match["part"]]
    due = date(today.year, today.month, _part_day(today.year, today.month, part))
    if due < today:
        year, month = _shift_month(today.year, today.month, 1)
        due = date(year, month, _part_day(year, month, part))
    return _Atom(match.group(0), due, DueType.PERIOD)


def _atom_year_word(match: re.Match[str], today: date) -> _Atom:
    if match["fy"]:
        year = today.year if today.month <= FISCAL_YEAR_END_MONTH else today.year + 1
        due = date(year, FISCAL_YEAR_END_MONTH, _month_len(year, FISCAL_YEAR_END_MONTH))
    else:
        due = date(today.year, 12, 31)
    return _Atom(match.group(0), due, DueType.MONTH_END)


def _atom_urgent(match: re.Match[str], today: date) -> _Atom:
    days = VERY_URGENT_OFFSET_DAYS if match["very"] else URGENT_OFFSET_DAYS
    return _Atom(match.group(0), today + timedelta(days=days), DueType.URGENT)


def _atom_rel_day(match: re.Match[str], today: date) -> _Atom:
    for days, name in ((3, "d3"), (2, "d2"), (1, "d1"), (0, "d0")):
        if match[name]:
            return _Atom(match.group(0), today + timedelta(days=days), DueType.RELATIVE)
    raise AssertionError("unreachable")  # 正規表現の定義上ここには来ない


def _atom_soon(match: re.Match[str], today: date) -> _Atom:
    return _Atom(match.group(0), today + timedelta(days=SOON_OFFSET_DAYS), DueType.SOON)


# 上から順に当て、当たった部分は消してから次へ進む（同じ文字を2回読まない）
_ATOM_RULES: tuple[tuple[re.Pattern[str], Callable[[re.Match[str], date], _Atom]], ...] = (
    (_ERA_FULL_RE, _atom_full_date),
    (_ERA_LETTER_RE, _atom_full_date),
    (_ERA_MONTH_RE, _atom_year_month),
    (_YEAR_FULL_RE, _atom_full_date),
    (_YEAR_MONTH_RE, _atom_year_month),
    (_SLASH_RE, _atom_month_day),
    (_MONTH_DAY_RE, _atom_month_day),
    (_REL_MONTH_DAY_RE, _atom_rel_month_day),
    (_MONTH_RE, _atom_month),
    (_AFTER_N_RE, _atom_after_n),
    (_DAY_RE, _atom_day),
    (_WEEK_DAY_RE, _atom_week_day),
    (_WEEK_RE, _atom_week),
    (_WEEKEND_RE, _atom_weekend),
    (_WEEKDAY_RE, _atom_weekday),
    (_REL_MONTH_RE, _atom_rel_month),
    (_MONTH_END_RE, _atom_month_end),
    (_BARE_PART_RE, _atom_bare_part),
    (_YEAR_WORD_RE, _atom_year_word),
    (_URGENT_RE, _atom_urgent),
    (_REL_DAY_RE, _atom_rel_day),
    (_SOON_RE, _atom_soon),
)


def _start_of(due: date, due_type: DueType) -> date:
    """期間の終わりの日から、始まりの日を求める（「以降・から」用）"""
    if due_type is DueType.WEEK:
        return _monday(due)
    if due_type is DueType.MONTH_END:
        return due.replace(day=1)
    if due_type is DueType.PERIOD:
        if due.day == EARLY_PART_DAY:
            return due.replace(day=1)
        if due.day == MIDDLE_PART_DAY:
            return due.replace(day=EARLY_PART_DAY + 1)
        return due.replace(day=MIDDLE_PART_DAY + 1)
    return due


def _read_time(match: re.Match[str]) -> tuple[Optional[time], Optional[str]]:
    """時刻を読む。(時刻, 要確認の理由) を返す。読めなければ時刻は None"""
    hour = int(match["h"])
    if match["half"]:
        minute = 30
    else:
        minute = int(match["min"] or match["min2"] or 0)
    ampm = (match["ampm"] or "").upper()
    note: Optional[str] = None
    if ampm in ("午後", "PM") and hour < 12:
        hour += 12
    elif ampm in ("午前", "AM") and hour == 12:
        hour = 0
    elif not ampm and 1 <= hour <= AFTERNOON_GUESS_MAX_HOUR:
        hour += 12
        note = f"「{match.group(0).strip()}」は午後の{hour}:{minute:02d}にしました（午前なら「午前」と書いてください）"
    if hour == 24 and minute == 0:
        return time(23, 59), None  # 「24時まで」はその日の終わり
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, f"時刻「{match.group(0).strip()}」が読めないので、時刻なしにしました"
    return time(hour, minute), note


# ═══════════════════════════════════════════════════════════════
# メインAPI
# ═══════════════════════════════════════════════════════════════

def parse_due_expression(
    raw: str,
    today: Optional[date] = None,
) -> DateParseResult:
    """
    括弧内（またはそれに準ずる）テキストから期限を解釈する。

    Parameters
    ----------
    raw : str
        括弧内のテキスト（例: "3/15まで", "5月中", "早め", "来週火曜 15時"）
    today : date | None
        基準日。省略時は実行日。

    Returns
    -------
    DateParseResult
        期限の形が無ければ due_type=NONE（題名に残す）。
        期限らしいが読めない・存在しない日付なら due_type=UNKNOWN・needs_review=True。
    """
    if today is None:
        today = date.today()

    raw_text = raw.strip()
    text = _normalize(raw)
    notes: list[str] = []

    # (1) 日付の後ろの曜日の注記 (月) (祝) を取り出す（祝日かどうかは確かめない）
    weekday_hints: list[str] = []

    def take_hint(match: re.Match[str]) -> str:
        if match["wd"]:
            weekday_hints.append(match["wd"])
        return " "

    work = _WEEKDAY_NOTE_RE.sub(take_hint, text)

    # (2) 時刻
    times: list[time] = []
    time_failed = False

    def take_time(match: re.Match[str]) -> str:
        nonlocal time_failed
        value, note = _read_time(match)
        if value is None:
            time_failed = True
        else:
            times.append(value)
        if note:
            notes.append(note)
        return " "

    if _NOON_RE.search(work):
        times.append(time(12, 0))
        work = _NOON_RE.sub(" ", work)
    work = _TIME_RE.sub(take_time, work)
    all_day = "終日" in work

    # (3) 日付の部品を上から順に取り出す
    atoms: list[_Atom] = []
    for pattern, reader in _ATOM_RULES:

        def take_atom(match: re.Match[str], reader=reader) -> str:
            atoms.append(reader(match, today))
            return "|"

        work = pattern.sub(take_atom, work)

    if not atoms:
        if times:
            atoms.append(_Atom("時刻だけ", today, DueType.RELATIVE))  # 時刻だけなら今日
        elif time_failed:
            return DateParseResult(
                None, DueType.UNKNOWN, raw_text, needs_review=True,
                warnings=tuple(notes), recognized=True,
            )
        elif _DUE_HINT_RE.search(text):
            message = f"「{raw_text}」は期限として読めませんでした（書き方を確かめてください）"
            return DateParseResult(
                None, DueType.UNKNOWN, raw_text, needs_review=True, warnings=(message,),
            )
        else:
            return DateParseResult(None, DueType.NONE, raw_text)

    valid = [atom for atom in atoms if atom.due is not None]
    if not valid:
        message = f"「{raw_text}」は存在しない日付なので、期限なしにしました"
        return DateParseResult(
            None, DueType.UNKNOWN, raw_text, needs_review=True, warnings=(message,), recognized=True,
        )
    if len(valid) < len(atoms):
        broken = next(atom.text for atom in atoms if atom.due is None)
        notes.append(f"「{broken}」は存在しない日付なので、読み飛ばしました")

    # (4) 日付が2つ以上なら、期間（〜・から）は終わりの日、それ以外はいちばん早い日
    dates = sorted({atom.due for atom in valid if atom.due is not None})
    if len(dates) == 1:
        chosen = valid[0]
    elif len(dates) == 2 and _RANGE_RE.search(text):
        chosen = next(atom for atom in valid if atom.due == dates[-1])
        notes.append(f"期間の書き方なので、終わりの日の{_md(dates[-1])}にしました")
    else:
        chosen = next(atom for atom in valid if atom.due == dates[0])
        notes.append(f"日付が2つ以上あります（いちばん早い{_md(dates[0])}にしました）")

    due = chosen.due
    assert due is not None
    due_type = chosen.due_type
    is_after = len(dates) == 1 and bool(_AFTER_RE.search(text))
    if not (is_after and due_type is DueType.MONTH_END):
        # 「11月から」は 11/1 からと決まるので、「月だけなので月末」の注意は要らない
        notes.extend(chosen.notes)
    if is_after:
        # 「以降・から」は、その期間の始まりの日（来週から → 来週の月曜、11月から → 11/1）
        due = _start_of(due, due_type)
        due_type = DueType.AFTER

    # (5) 要確認の理由を集める
    if today.weekday() == 6:
        week_word = next((atom.text for atom in valid if atom.week_based), None)
        if week_word:
            notes.append(f"日曜日に書いた「{week_word}」は、月曜始まりの週で数えました（{_md(due)}）")
    unsure = _UNSURE_RE.search(work)
    if unsure:
        notes.append(f"「{unsure.group(0)}」があいまいなので、日付を確かめてください")
    actual = WEEKDAY_NAMES[due.weekday()]
    for hint in weekday_hints:
        if hint != actual:
            notes.append(f"{_md(due)}は{actual}曜日です（書かれた曜日は{hint}）")
    overdue = due < today and due_type is not DueType.AFTER
    if overdue:
        notes.append(f"期限の{_ymd(due)}を過ぎています")

    due_time: Optional[time] = None
    if times and not all_day:
        due_time = min(times)
        if len(set(times)) > 1:
            notes.append(f"時刻が2つ以上あります（早い{due_time:%H:%M}にしました）")

    return DateParseResult(
        due_date=due,
        due_type=due_type,
        raw_text=raw_text,
        due_time=due_time,
        needs_review=bool(notes),
        overdue=overdue,
        warnings=tuple(notes),
        recognized=True,
    )


# ═══════════════════════════════════════════════════════════════
# 行の中から期限の括弧を探す
# ═══════════════════════════════════════════════════════════════

# 丸括弧（全角・半角）。中に (月) のような短い括弧を1段だけ入れてよい
_PAREN_RE = re.compile(
    r"[(（](?P<body>[^()（）]*(?:[(（][^()（）]{1,6}[)）][^()（）]*)*)[)）]"
)

# 括弧の外にある「期限らしい書き方」（読まずに、要確認の印だけ付ける）
_OUTSIDE_DUE_RE = re.compile(
    r"(?:\d{1,2}\s*/\s*\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*日|今日|本日|明日|明後日"
    r"|今週|来週|再来週|今月|来月|月末|年内|[月火水木金土日]曜日?)\s*(?:中に|までに|まで|迄)"
)

NO_TITLE_WARNING = "題名がありません（期限だけが書かれています）"


def parse_due_in_line(line: str, today: Optional[date] = None) -> LineDueResult:
    """
    タスクの1行から期限を取り出し、期限の括弧を除いた題名と一緒に返す。

    - 期限は丸括弧（全角・半角）の中に書く。括弧はいくつあってもよい。
    - 期限の形として読めた括弧（存在しない日付も含む）は題名から除く。
      期限と関係のない括弧（第2版など）と、期限らしいが読めない括弧は題名に残す。
    - 期限の括弧が2つ以上なら、いちばん早い日を採り、要確認にする。
    - 注意（warnings）が1つでもあれば needs_review=True。行を捨てることはない。

    Parameters
    ----------
    line : str
        タスク1行（例: "資料作り (3/15まで)"）
    today : date | None
        基準日。省略時は実行日。
    """
    if today is None:
        today = date.today()

    found: list[tuple[re.Match[str], DateParseResult]] = []
    for match in _PAREN_RE.finditer(line):
        result = parse_due_expression(match["body"], today=today)
        if result.due_type is not DueType.NONE:
            found.append((match, result))

    title = line
    for match, result in reversed(found):
        if result.recognized:
            title = title[: match.start()] + title[match.end():]
    title = title.strip()

    warnings: list[str] = []
    chosen: Optional[DateParseResult] = None
    if len(found) == 1:
        chosen = found[0][1]
        warnings.extend(chosen.warnings)
    elif found:
        dated = [result for _, result in found if result.due_date is not None]
        if dated:
            chosen = min(dated, key=lambda r: (r.due_date, r.due_time or time.max))
        else:
            chosen = found[0][1]
        for _, result in found:
            warnings.extend(result.warnings)
        where = f"いちばん早い{_md(chosen.due_date)}" if chosen.due_date else "最初のもの"
        warnings.append(f"期限が2つ以上書かれています（{where}にしました）")

    outside = _OUTSIDE_DUE_RE.search(_normalize(_PAREN_RE.sub(" ", title)))
    if outside:
        warnings.append(
            f"括弧の外の「{outside.group(0)}」は期限として読んでいません（期限は括弧の中に書いてください）"
        )

    if not title and line.strip():
        # 期限だけの行は、元の文字をそのまま題名にする
        title = line.strip()
        warnings.append(NO_TITLE_WARNING)

    if chosen is None:
        return LineDueResult(
            title=title, due_date=None, due_type=DueType.NONE, due_raw="",
            needs_review=bool(warnings), warnings=tuple(warnings),
        )
    return LineDueResult(
        title=title,
        due_date=chosen.due_date,
        due_type=chosen.due_type,
        due_raw=chosen.raw_text,
        due_time=chosen.due_time,
        needs_review=bool(warnings),
        overdue=chosen.overdue,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class DueMention:
    """文の中で見つかった日付の書き方1つ（find_due_mentions の結果）"""
    text: str  # 当たった文字（NFKC で半角にそろえた後）
    start: int  # NFKC 後の文字列での位置
    end: int
    due_date: Optional[date]  # 存在しない日付なら None
    due_type: DueType


def find_due_mentions(text: str, today: Optional[date] = None) -> list[DueMention]:
    """
    括弧の外も含めて、文の中の日付の書き方を全部さがす（急ぎの検出 urgency.py 用）。

    読み方は parse_due_expression と同じ規則（_ATOM_RULES）。位置は
    unicodedata.normalize("NFKC", text) の文字列での位置。前から順に並べて返す。
    """
    if today is None:
        today = date.today()
    normalized = unicodedata.normalize("NFKC", text)
    work = normalized
    mentions: list[DueMention] = []
    for pattern, reader in _ATOM_RULES:
        for match in pattern.finditer(work):
            atom = reader(match, today)
            mentions.append(DueMention(
                text=normalized[match.start():match.end()],
                start=match.start(),
                end=match.end(),
                due_date=atom.due,
                due_type=atom.due_type,
            ))
        # 同じ長さの埋め草で消す（位置をずらさない・同じ文字を2回読まない）
        work = pattern.sub(lambda match: "\x00" * len(match.group(0)), work)
    mentions.sort(key=lambda mention: mention.start)
    return mentions


def extract_due_part(line: str) -> tuple[str, str]:
    """
    行テキストから期限部分を抽出し、(本文, 期限テキスト) を返す（互換用）。

    中身は parse_due_in_line と同じ。期限が無ければ期限テキストは ""。
    """
    result = parse_due_in_line(line)
    return result.title, result.due_raw
