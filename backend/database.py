"""
============================================================
データベース管理
============================================================
タスク履歴の保存と検索（SQLite）

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: なし（標準ライブラリのみ）
============================================================
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import logging

from backend.models import Task, Category

logger = logging.getLogger(__name__)

# データベースファイルのパス
DB_PATH = Path("task_sync.db")


class TaskDatabase:
    """タスクデータベース管理クラス"""
    
    def __init__(self, db_path: Path = DB_PATH):
        """
        初期化
        
        Args:
            db_path: データベースファイルのパス
        """
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """データベースとテーブルを初期化"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # タスクテーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    deadline TEXT,
                    category TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    synced_to_calendar BOOLEAN DEFAULT 0
                )
            """)
            
            # インデックス作成
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_category 
                ON tasks(category)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_deadline 
                ON tasks(deadline)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON tasks(created_at DESC)
            """)
            
            conn.commit()
            logger.info(f"✅ データベース初期化完了: {self.db_path}")
    
    def save_task(self, task: Task, synced: bool = False) -> int:
        """
        タスクを保存
        
        Args:
            task: 保存するタスク
            synced: カレンダーに同期済みか
            
        Returns:
            int: 保存されたタスクのID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO tasks (title, deadline, category, raw_text, created_at, synced_to_calendar)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                task.title,
                task.deadline.isoformat() if task.deadline else None,
                task.category.value,
                task.raw_text,
                datetime.now().isoformat(),
                synced
            ))
            
            conn.commit()
            task_id = cursor.lastrowid
            logger.info(f"💾 タスク保存: ID={task_id}, title={task.title}")
            return task_id
    
    def get_recent_tasks(self, limit: int = 50) -> List[dict]:
        """
        最近のタスクを取得
        
        Args:
            limit: 取得件数
            
        Returns:
            タスクのリスト
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM tasks
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def search_tasks(
        self, 
        keyword: Optional[str] = None,
        category: Optional[Category] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[dict]:
        """
        タスクを検索
        
        Args:
            keyword: キーワード（タイトル検索）
            category: カテゴリフィルター
            date_from: 期限の開始日
            date_to: 期限の終了日
            
        Returns:
            検索結果のリスト
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM tasks WHERE 1=1"
            params = []
            
            if keyword:
                query += " AND (title LIKE ? OR raw_text LIKE ?)"
                params.extend([f"%{keyword}%", f"%{keyword}%"])
            
            if category:
                query += " AND category = ?"
                params.append(category.value)
            
            if date_from:
                query += " AND deadline >= ?"
                params.append(date_from.isoformat())
            
            if date_to:
                query += " AND deadline <= ?"
                params.append(date_to.isoformat())
            
            query += " ORDER BY created_at DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_statistics(self) -> dict:
        """
        統計情報を取得
        
        Returns:
            統計データ
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 総タスク数
            cursor.execute("SELECT COUNT(*) FROM tasks")
            total = cursor.fetchone()[0]
            
            # カテゴリ別集計
            cursor.execute("""
                SELECT category, COUNT(*) as count
                FROM tasks
                GROUP BY category
            """)
            by_category = dict(cursor.fetchall())
            
            # 同期済み/未同期
            cursor.execute("""
                SELECT synced_to_calendar, COUNT(*) as count
                FROM tasks
                GROUP BY synced_to_calendar
            """)
            sync_stats = dict(cursor.fetchall())
            
            # 今月のタスク数
            cursor.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE created_at >= date('now', 'start of month')
            """)
            this_month = cursor.fetchone()[0]
            
            return {
                "total": total,
                "by_category": by_category,
                "synced": sync_stats.get(1, 0),
                "not_synced": sync_stats.get(0, 0),
                "this_month": this_month
            }
    
    def mark_as_synced(self, task_id: int):
        """
        タスクを同期済みとしてマーク
        
        Args:
            task_id: タスクID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks
                SET synced_to_calendar = 1
                WHERE id = ?
            """, (task_id,))
            conn.commit()
            logger.info(f"✅ タスクを同期済みにマーク: ID={task_id}")


# グローバルインスタンス
db = TaskDatabase()
