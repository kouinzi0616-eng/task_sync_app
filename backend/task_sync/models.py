"""
============================================================
models.py — データモデル定義
============================================================
タスク・同期結果のPydanticモデル。

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: pydantic
============================================================
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


# ═══════════════════════════════════════════════════════════════
# カテゴリ列挙型
# ═══════════════════════════════════════════════════════════════

class TaskCategory(str, Enum):
    """タスクのカテゴリ（Googleカレンダー上のカレンダー名に対応）"""
    TEMPLE = "寺院関係"
    SEIHOUKAI = "青鳳会"
    EIDOUBU = "詠道部"
    PERSONAL = "個人"


# ═══════════════════════════════════════════════════════════════
# 期限の曖昧さ列挙型
# ═══════════════════════════════════════════════════════════════

class DueType(str, Enum):
    """期限表現の種類（監査ログ用に原文を保持する判定材料）"""
    EXACT = "exact"          # M/Dまで, D日まで
    MONTH_END = "month_end"  # M月まで, M月中
    SOON = "soon"            # 早め / なるべく早め
    AFTER = "after"          # D日以降
    NONE = "none"            # 期限指定なし


# ═══════════════════════════════════════════════════════════════
# Taskモデル
# ═══════════════════════════════════════════════════════════════

class Task(BaseModel):
    """正規化されたタスク"""

    source_text: str = Field(..., description="パース元の原文1行")
    title: str = Field(..., description="正規化後のタスク名")
    category: TaskCategory = Field(..., description="自動判定カテゴリ")
    due_date: date = Field(..., description="算出した期限日")
    due_type: DueType = Field(DueType.NONE, description="期限表現の種類")
    due_raw: str = Field("", description="期限部分の原文（括弧内テキスト）")

    @computed_field  # type: ignore[misc]
    @property
    def task_id(self) -> str:
        """カテゴリ＋正規化タイトル＋期限日から安定ハッシュを生成"""
        seed = f"{self.category.value}|{self.title}|{self.due_date.isoformat()}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    @property
    def description_text(self) -> str:
        """Googleカレンダーの description に書き込む内容"""
        lines = [
            f"【原文】{self.source_text}",
            f"【カテゴリ】{self.category.value}",
            f"【期限種別】{self.due_type.value}",
        ]
        if self.due_raw:
            lines.append(f"【期限原文】{self.due_raw}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 同期結果モデル
# ═══════════════════════════════════════════════════════════════

class SyncAction(str, Enum):
    """upsert の結果アクション"""
    INSERT = "insert"
    UPDATE = "update"
    SKIP = "skip"   # dry-run 時


class SyncResult(BaseModel):
    """1タスク分の同期結果"""
    task: Task
    action: SyncAction
    calendar_event_id: Optional[str] = None
    error: Optional[str] = None
