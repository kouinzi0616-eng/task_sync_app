"""
============================================================
parser.py — 自然文タスクリストのパーサー
============================================================
テキスト行を解析し、Taskモデルのリストを返す。

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
============================================================
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from .date_rules import extract_due_part, parse_due_expression
from .models import DueType, Task
from .normalizer import classify_category

logger = logging.getLogger("task_sync")

# ═══════════════════════════════════════════════════════════════
# 定数
# ═══════════════════════════════════════════════════════════════

# 行頭のマーカー（箇条書き記号）を除去するパターン
_BULLET_PATTERN = re.compile(
    r"^[\s]*[-・●■□▶▷★☆✓✔☐→▸►※◯○◎]+[\s　]*"
)

# 空行・コメント行を無視する判定
_SKIP_PATTERN = re.compile(r"^[\s]*$|^[\s]*#")


# ═══════════════════════════════════════════════════════════════
# パーサー
# ═══════════════════════════════════════════════════════════════

def _clean_line(line: str) -> str:
    """行頭の箇条書き記号を除去し、前後の空白をトリムする"""
    return _BULLET_PATTERN.sub("", line).strip()


def parse_line(
    line: str,
    today: Optional[date] = None,
) -> Optional[Task]:
    """
    1行のテキストをパースしてTaskモデルを返す。

    Parameters
    ----------
    line : str
        入力テキスト1行
    today : date | None
        基準日（テスト用）

    Returns
    -------
    Task | None
        パース不能（空行等）の場合はNone
    """
    if _SKIP_PATTERN.match(line):
        return None

    source_text = line.strip()
    cleaned = _clean_line(source_text)
    if not cleaned:
        return None

    # 期限部分を抽出
    body, due_text = extract_due_part(cleaned)
    if not body:
        return None

    # 期限解釈
    if due_text:
        result = parse_due_expression(due_text, today=today)
        due_date = result.due_date
        due_type = result.due_type
        due_raw = result.raw_text
    else:
        # 括弧による期限指定なし
        from .date_rules import NO_DEADLINE_OFFSET_DAYS
        from datetime import timedelta

        base = today or date.today()
        due_date = base + timedelta(days=NO_DEADLINE_OFFSET_DAYS)
        due_type = DueType.NONE
        due_raw = ""

    # カテゴリ判定
    category = classify_category(body)

    # タイトル正規化（余分な空白を1つに）
    title = re.sub(r"\s+", " ", body)

    logger.debug(
        "パース結果: title=%s, category=%s, due=%s (%s)",
        title, category.value, due_date, due_type.value,
    )

    return Task(
        source_text=source_text,
        title=title,
        category=category,
        due_date=due_date,
        due_type=due_type,
        due_raw=due_raw,
    )


def parse_text(
    text: str,
    today: Optional[date] = None,
) -> list[Task]:
    """
    複数行のテキストをパースし、Taskリストを返す。

    Parameters
    ----------
    text : str
        改行区切りのタスクリスト
    today : date | None
        基準日

    Returns
    -------
    list[Task]
    """
    tasks: list[Task] = []
    for line_num, line in enumerate(text.splitlines(), start=1):
        try:
            task = parse_line(line, today=today)
            if task is not None:
                tasks.append(task)
        except ValueError as exc:
            logger.warning("行 %d のパースに失敗: %s — %s", line_num, line.strip(), exc)
    logger.info("パース完了: %d行 → %dタスク", len(text.splitlines()), len(tasks))
    return tasks
