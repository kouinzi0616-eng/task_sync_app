"""
============================================================
カテゴリ分類器
============================================================
タスクテキストから適切なカテゴリを推定

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: pydantic
============================================================
"""
from __future__ import annotations

from backend.models import Category


# カテゴリごとのキーワード辞書
CATEGORY_KEYWORDS = {
    Category.TEMPLE: [
        "法要", "お経", "葬儀", "法事", "檀家", "檀信徒", "お寺", "寺院",
        "本堂", "境内", "墓地", "供養", "仏事", "僧侶", "住職", "お布施",
        "御朱印", "参拝", "お参り", "護摩", "祈祷", "年忌", "盆", "彼岸"
    ],
    Category.SEIHOUKAI: [
        "青鳳会", "せいほうかい", "セイホウカイ", "会議", "理事会",
        "総会", "役員", "幹事", "会報", "行事", "イベント企画"
    ],
    Category.EIDOUBU: [
        "詠道部", "えいどうぶ", "エイドウブ", "詠唱", "和歌", "短歌",
        "御詠歌", "詠み", "稽古", "練習", "発表会", "奉詠"
    ],
    Category.PERSONAL: [
        "買い物", "病院", "美容院", "歯医者", "旅行", "予約", "家族",
        "友人", "プライベート", "個人的", "趣味", "習い事"
    ]
}


def classify_category(text: str) -> Category:
    """
    タスクテキストからカテゴリを分類
    
    ロジック:
    1. 各カテゴリのキーワードとマッチング
    2. マッチ数が最も多いカテゴリを選択
    3. 同点の場合は優先順位（寺院 > 青鳳会 > 詠道部 > 個人）
    
    Args:
        text: タスクテキスト
        
    Returns:
        Category: 推定されたカテゴリ
    """
    # 小文字化してマッチング精度を上げる
    text_lower = text.lower()
    
    # 各カテゴリのマッチスコアを計算
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in text_lower)
        scores[category] = score
    
    # スコアが最も高いカテゴリを返す
    max_score = max(scores.values())
    
    if max_score == 0:
        # どのキーワードにもマッチしない場合はデフォルトで「個人」
        return Category.PERSONAL
    
    # 同点の場合は優先順位で決定
    priority = [Category.TEMPLE, Category.SEIHOUKAI, Category.EIDOUBU, Category.PERSONAL]
    for cat in priority:
        if scores[cat] == max_score:
            return cat
    
    # フォールバック（通常ここには来ない）
    return Category.PERSONAL
