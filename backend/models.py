"""
============================================================
データモデル定義
============================================================
タスクとカテゴリのPydanticモデル

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: pydantic
============================================================
"""
from __future__ import annotations

from enum import Enum

# 履歴保存（backend/database.py）だけが使っていた Task モデルは、B29 で database.py と一緒に削除した。
# タスクは画面（frontend/）が端末の中（IndexedDB）に保存する。方針は docs/storage.md。


class Category(str, Enum):
    """タスクカテゴリ"""
    TEMPLE = "寺院関係"
    SEIHOUKAI = "青鳳会"
    EIDOUBU = "詠道部"
    PERSONAL = "個人"
