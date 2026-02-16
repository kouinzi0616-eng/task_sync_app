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

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .models import DueType

# ═══════════════════════════════════════════════════════════════
# 定数（マジックナンバー禁止）
# ═══════════════════════════════════════════════════════════════

# 「早め」「なるべく早め」の場合、今日から何日後をデフォルト期限とするか
SOON_OFFSET_DAYS = 3

# 期限指定なしの場合、今日から何日後をデフォルト期限とするか
NO_DEADLINE_OFFSET_DAYS = 1


# ═══════════════════════════════════════════════════════════════
# 解釈結果
# ═══════════════════════════════════════════════════════════════

@dataclass
class DateParseResult:
    """日付解釈の結果"""
    due_date: date
    due_type: DueType
    raw_text: str  # 括弧内の原文


# ═══════════════════════════════════════════════════════════════
# 正規表現パターン（優先度順）
# ═══════════════════════════════════════════════════════════════

# (3/15まで) (3/15) — M/D形式
_PAT_SLASH_DATE = re.compile(
    r"(\d{1,2})\s*/\s*(\d{1,2})\s*(?:まで)?",
)

# (3月15日まで) (15日まで) — 漢字形式
_PAT_MD_KANJI = re.compile(
    r"(?:(\d{1,2})月)?(\d{1,2})日\s*(?:まで)?",
)

# (3月まで) (3月中) — 月末
_PAT_MONTH_END = re.compile(
    r"(\d{1,2})月\s*(?:まで|中)",
)

# (15日以降) (3/15以降) — 以降
_PAT_AFTER_KANJI = re.compile(
    r"(?:(\d{1,2})月)?(\d{1,2})日\s*以降",
)
_PAT_AFTER_SLASH = re.compile(
    r"(\d{1,2})\s*/\s*(\d{1,2})\s*以降",
)

# (早め) (なるべく早め) (なるべく早く) (至急)
_PAT_SOON = re.compile(
    r"(?:なるべく)?早[めく]|至急|ASAP",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════
# ヘルパー
# ═══════════════════════════════════════════════════════════════

def _resolve_year(month: int, day: int, today: date) -> date:
    """年を補完する。過去2ヶ月以上前なら翌年と解釈"""
    # 月境界の猶予（過去2ヶ月は「今年」扱い）
    PAST_MONTH_GRACE = 2
    candidate = date(today.year, month, day)
    if candidate < today - timedelta(days=PAST_MONTH_GRACE * 31):
        candidate = date(today.year + 1, month, day)
    return candidate


def _month_last_day(year: int, month: int) -> date:
    """指定年月の末日を返す"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


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
        括弧内のテキスト（例: "3/15まで", "5月中", "早め"）
    today : date | None
        基準日。省略時は実行日。

    Returns
    -------
    DateParseResult
    """
    if today is None:
        today = date.today()

    text = raw.strip()

    # --- (D日以降) / (M/D以降) ---
    match = _PAT_AFTER_SLASH.search(text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        due = _resolve_year(month, day, today)
        return DateParseResult(due_date=due, due_type=DueType.AFTER, raw_text=raw)

    match = _PAT_AFTER_KANJI.search(text)
    if match:
        month = int(match.group(1)) if match.group(1) else today.month
        day = int(match.group(2))
        due = _resolve_year(month, day, today)
        return DateParseResult(due_date=due, due_type=DueType.AFTER, raw_text=raw)

    # --- (M月まで) (M月中) → 月末 ---
    match = _PAT_MONTH_END.search(text)
    if match:
        month = int(match.group(1))
        year = today.year if month >= today.month else today.year + 1
        due = _month_last_day(year, month)
        return DateParseResult(due_date=due, due_type=DueType.MONTH_END, raw_text=raw)

    # --- (M/Dまで) ---
    match = _PAT_SLASH_DATE.search(text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        due = _resolve_year(month, day, today)
        return DateParseResult(due_date=due, due_type=DueType.EXACT, raw_text=raw)

    # --- (M月D日まで) (D日まで) ---
    match = _PAT_MD_KANJI.search(text)
    if match:
        month = int(match.group(1)) if match.group(1) else today.month
        day = int(match.group(2))
        due = _resolve_year(month, day, today)
        return DateParseResult(due_date=due, due_type=DueType.EXACT, raw_text=raw)

    # --- (早め) (なるべく早め) (至急) ---
    if _PAT_SOON.search(text):
        due = today + timedelta(days=SOON_OFFSET_DAYS)
        return DateParseResult(due_date=due, due_type=DueType.SOON, raw_text=raw)

    # --- 該当パターンなし → 期限なし扱い ---
    due = today + timedelta(days=NO_DEADLINE_OFFSET_DAYS)
    return DateParseResult(due_date=due, due_type=DueType.NONE, raw_text=raw)


def extract_due_part(line: str) -> tuple[str, str]:
    """
    行テキストから括弧で囲まれた期限部分を抽出し、
    (本文, 期限テキスト) を返す。

    括弧は全角・半角の丸括弧に対応。
    """
    # 全角括弧を半角に統一
    normalized = line.replace("（", "(").replace("）", ")")
    match = re.search(r"\(([^)]+)\)\s*$", normalized)
    if match:
        due_text = match.group(1)
        body = normalized[: match.start()].strip()
        return body, due_text

    return line.strip(), ""
