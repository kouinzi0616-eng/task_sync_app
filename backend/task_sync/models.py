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


# カテゴリは B27 で設定（JSON）から決めるようにした。名前の一覧はコードに書かない。
# 判定の正本は categories.py（設定の読み先と見本は README の「カテゴリの設定」）。


# ═══════════════════════════════════════════════════════════════
# 期限の曖昧さ列挙型
# ═══════════════════════════════════════════════════════════════

class DueType(str, Enum):
    """期限表現の種類（監査ログ用に原文を保持する判定材料）。

    値の文字列は API の応答（due_type）と検算表（tests/fixtures/due_cases.json）でも使う。
    """
    EXACT = "exact"          # M/Dまで, M月D日, D日まで, 2026/3/15, 令和8年3月15日
    MONTH_END = "month_end"  # M月まで, M月中, 月末, 今月中, 来月末, 年内, 年度末
    PERIOD = "period"        # 上旬（10日）・中旬（20日）・下旬（末日）
    WEEK = "week"            # 今週中, 来週まで, 再来週（その週の日曜。週は月曜始まり）
    RELATIVE = "relative"    # 今日, 明日, 明後日, 3日後, 金曜, 来週火曜, 時刻だけ
    URGENT = "urgent"        # 至急（翌日）, 大至急（今日）
    SOON = "soon"            # 早め / なるべく早め（3日後）
    AFTER = "after"          # D日以降
    UNKNOWN = "unknown"      # 期限らしいが読めない・存在しない日付（要確認）
    NONE = "none"            # 期限指定なし


# ═══════════════════════════════════════════════════════════════
# Taskモデル
# ═══════════════════════════════════════════════════════════════

class Task(BaseModel):
    """正規化されたタスク"""

    source_text: str = Field(..., description="パース元の原文1行")
    title: str = Field(..., description="正規化後のタスク名")
    category: str = Field(..., description="自動判定カテゴリ（設定にあるカテゴリ名）")
    category_hits: list[str] = Field(default_factory=list, description="カテゴリの判定で当たった語（空なら既定のカテゴリ）")
    due_date: date = Field(..., description="算出した期限日")
    due_type: DueType = Field(DueType.NONE, description="期限表現の種類")
    due_raw: str = Field("", description="期限部分の原文（括弧内テキスト）")
    needs_review: bool = Field(False, description="人が確かめるべき行か（読めない・あいまい・期限切れなど）")
    warnings: list[str] = Field(default_factory=list, description="要確認の理由（利用者に見せる文）")

    @computed_field  # type: ignore[misc]
    @property
    def task_id(self) -> str:
        """カテゴリ＋正規化タイトル＋期限日から安定ハッシュを生成"""
        seed = f"{self.category}|{self.title}|{self.due_date.isoformat()}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    @property
    def description_text(self) -> str:
        """Googleカレンダーの description に書き込む内容"""
        lines = [
            f"【原文】{self.source_text}",
            f"【カテゴリ】{self.category}",
            f"【期限種別】{self.due_type.value}",
        ]
        if self.category_hits:
            lines.insert(2, f"【カテゴリの理由】{'・'.join(self.category_hits)}")
        if self.due_raw:
            lines.append(f"【期限原文】{self.due_raw}")
        for warning in self.warnings:
            lines.append(f"【要確認】{warning}")
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
