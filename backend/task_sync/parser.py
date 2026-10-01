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
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .date_rules import NO_DEADLINE_OFFSET_DAYS, parse_due_in_line
from .models import Task
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

# parse_text が1行ごとに返す状態
STATUS_TASK = "task"  # タスクとして読めた（needs_review の行も含む）
STATUS_SKIPPED = "skipped"  # 空行・コメント・記号だけの行（タスクではない）
STATUS_ERROR = "error"  # 思わぬ例外。行は捨てずに、この状態で返す

ROW_ERROR_MESSAGE = "この行は解析できませんでした"


# ═══════════════════════════════════════════════════════════════
# 1行ごとの結果
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LineResult:
    """parse_text が入力の1行ごとに返す結果（入力の行数 = 結果の数）"""
    line_no: int  # 1 始まり
    source_text: str  # 入力の行そのまま
    status: str  # STATUS_TASK / STATUS_SKIPPED / STATUS_ERROR
    task: Optional[Task] = None
    reason: str = ""  # skipped・error の理由

    @property
    def needs_review(self) -> bool:
        """人が確かめるべき行か（失敗した行も True）"""
        if self.status == STATUS_ERROR:
            return True
        return bool(self.task and self.task.needs_review)


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
        空行・コメント行・記号だけの行は None。
        期限が読めない・存在しない日付の行も捨てずに、needs_review=True の Task を返す。
    """
    if _SKIP_PATTERN.match(line):
        return None

    source_text = line.strip()
    cleaned = _clean_line(source_text)
    if not cleaned:
        return None

    base = today or date.today()
    due = parse_due_in_line(cleaned, today=base)

    # カレンダーには日付が要るので、期限なし・読めない行は「翌日」に置く（要確認の印は残す）
    due_date = due.due_date or base + timedelta(days=NO_DEADLINE_OFFSET_DAYS)

    # タイトル正規化（余分な空白を1つに）
    title = re.sub(r"\s+", " ", due.title)

    # カテゴリ判定
    category = classify_category(title)

    # 題名などの行の文字はログに出さない（件数と種類だけ）
    logger.debug(
        "パース結果: category=%s, due=%s (%s), needs_review=%s",
        category.value, due_date, due.due_type.value, due.needs_review,
    )

    return Task(
        source_text=source_text,
        title=title,
        category=category,
        due_date=due_date,
        due_type=due.due_type,
        due_raw=due.due_raw,
        needs_review=due.needs_review,
        warnings=list(due.warnings),
    )


def parse_text(
    text: str,
    today: Optional[date] = None,
) -> list[LineResult]:
    """
    複数行のテキストをパースし、入力の1行ごとに LineResult を返す。

    入力の行数（text.splitlines() の数）と、返す結果の数は必ず等しい（黙って消える行は無い）。
    空行・コメントは status=skipped、読めない期限は Task の needs_review=True で返す。
    タスクだけが要るときは parse_tasks を使う。

    Parameters
    ----------
    text : str
        改行区切りのタスクリスト
    today : date | None
        基準日

    Returns
    -------
    list[LineResult]
    """
    results: list[LineResult] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        try:
            task = parse_line(line, today=today)
        except Exception as exc:  # 1行の失敗で全体を止めず、行も捨てない
            logger.warning("行 %d の解析に失敗（%s）", line_no, type(exc).__name__)
            results.append(LineResult(line_no, line, STATUS_ERROR, reason=ROW_ERROR_MESSAGE))
            continue
        if task is None:
            results.append(LineResult(line_no, line, STATUS_SKIPPED, reason="空行・コメント・記号だけの行"))
        else:
            results.append(LineResult(line_no, line, STATUS_TASK, task=task))

    task_count = sum(1 for result in results if result.task is not None)
    review_count = sum(1 for result in results if result.needs_review)
    error_count = sum(1 for result in results if result.status == STATUS_ERROR)
    logger.info(
        "パース完了: %d行 → タスク%d件（要確認%d件・失敗%d件・空行など%d件）",
        len(results), task_count, review_count, error_count,
        len(results) - task_count - error_count,
    )
    return results


def parse_tasks(
    text: str,
    today: Optional[date] = None,
) -> list[Task]:
    """parse_text の結果からタスクだけを取り出す（同期 sync_tasks に渡す用）"""
    return [result.task for result in parse_text(text, today=today) if result.task is not None]
