"""
============================================================
normalizer.py — カテゴリ自動判定
============================================================
タスク本文のキーワードからカテゴリを判定する。

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
============================================================
"""

from __future__ import annotations

from .models import TaskCategory

# ═══════════════════════════════════════════════════════════════
# カテゴリ判定キーワード辞書
# ═══════════════════════════════════════════════════════════════
# 優先度の高い順に評価する。最初にマッチしたカテゴリを採用。
# settings.yaml でオーバーライドする拡張も可能だが、
# v1.0 ではハードコードで十分。

CATEGORY_KEYWORDS: list[tuple[TaskCategory, list[str]]] = [
    (TaskCategory.SEIHOUKAI, [
        "青鳳会", "せいほうかい", "青鳳", "会報", "役員会",
    ]),
    (TaskCategory.EIDOUBU, [
        "詠道部", "えいどうぶ", "詠道", "和讃", "声明", "御詠歌",
    ]),
    (TaskCategory.TEMPLE, [
        "寺", "法要", "檀家", "御朱印", "本堂", "仏具",
        "お盆", "彼岸", "施餓鬼", "墓参", "永代",
        "住職", "副住職", "庫裏", "山門", "鐘楼",
        "法話", "護持会", "総代", "門信徒",
    ]),
    # 上記いずれにもマッチしなければ「個人」
]


def classify_category(text: str) -> TaskCategory:
    """
    テキスト本文からカテゴリを判定する。

    Parameters
    ----------
    text : str
        タスク本文（期限部分を除いたもの）

    Returns
    -------
    TaskCategory
    """
    for category, keywords in CATEGORY_KEYWORDS:
        for keyword in keywords:
            if keyword in text:
                return category
    return TaskCategory.PERSONAL
