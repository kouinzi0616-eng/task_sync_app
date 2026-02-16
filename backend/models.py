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

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    """タスクカテゴリ"""
    TEMPLE = "寺院関係"
    SEIHOUKAI = "青鳳会"
    EIDOUBU = "詠道部"
    PERSONAL = "個人"


class Task(BaseModel):
    """タスクモデル"""
    title: str = Field(..., description="タスクのタイトル")
    deadline: Optional[datetime] = Field(None, description="期限（終日イベント想定）")
    category: Category = Field(..., description="カテゴリ")
    raw_text: str = Field(..., description="元のテキスト（ログ用）")
    
    class Config:
        """Pydantic設定"""
        use_enum_values = True  # EnumをJSON化する際に値を使用
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
