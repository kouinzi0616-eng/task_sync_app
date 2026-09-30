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
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

# 日本時間のタイムゾーン（Windows では tzdata パッケージから読む）
JST = ZoneInfo('Asia/Tokyo')


def parse_date(text: str) -> Optional[datetime]:
    """
    日本語の日付表現を解析
    
    対応パターン:
    - (3/15まで) → 2026-03-15
    - (5月中) → 2026-05-31
    - (早め) → 3日後
    - (至急) → 明日
    - (来週まで) → 来週日曜日
    
    Args:
        text: 解析対象のテキスト
        
    Returns:
        datetime | None: 解析された日付（JST、時刻は00:00:00）
    """
    now = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # パターン1: (3/15まで) → 月/日
    match = re.search(r'\((\d{1,2})/(\d{1,2})まで\)', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = now.year
        
        # 過去の日付なら翌年と解釈
        result = now.replace(year=year, month=month, day=day)
        if result < now:
            result = result.replace(year=year + 1)
        
        return result
    
    # パターン2: (5月中) → 月末
    match = re.search(r'\((\d{1,2})月中\)', text)
    if match:
        month = int(match.group(1))
        year = now.year
        
        # その月の末日を取得
        if month == 12:
            result = now.replace(year=year, month=12, day=31)
        else:
            # 翌月1日の前日 = 今月の末日
            next_month = now.replace(year=year, month=month + 1, day=1)
            result = next_month - timedelta(days=1)
        
        # 過去なら翌年
        if result < now:
            result = result + relativedelta(years=1)
        
        return result
    
    # パターン3: (早め) → 3日後
    if '(早め)' in text or '(はやめ)' in text:
        return now + timedelta(days=3)
    
    # パターン4: (至急) → 明日
    if '(至急)' in text or '(しきゅう)' in text:
        return now + timedelta(days=1)
    
    # パターン5: (来週まで) → 来週日曜日
    if '(来週まで)' in text or '(来週)' in text:
        # 今日の曜日（月曜=0, 日曜=6）
        weekday = now.weekday()
        # 次の日曜日までの日数
        days_until_sunday = (6 - weekday) % 7
        if days_until_sunday == 0:
            days_until_sunday = 7  # 今日が日曜なら来週の日曜
        
        return now + timedelta(days=days_until_sunday + 7)
    
    # パターンにマッチしない場合はNone
    return None
