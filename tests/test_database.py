"""backend/database.py（今は API から使われていない履歴保存）の今の挙動を記録する。"""
from __future__ import annotations

import pytest


def test_database_save_task_currently_fails(tmp_path, monkeypatch):
    # import した時点で作業フォルダに task_sync.db を作るので、一時フォルダに移ってから読む
    monkeypatch.chdir(tmp_path)
    from backend.database import TaskDatabase
    from backend.models import Category, Task

    db = TaskDatabase(tmp_path / "test.db")
    task = Task(title="資料", deadline=None, category=Category.TEMPLE, raw_text="資料")

    # Task は use_enum_values のため category が文字列になり、save_task の .value で失敗する
    assert task.category == Category.TEMPLE.value
    with pytest.raises(AttributeError):
        db.save_task(task)

    assert db.get_recent_tasks() == []
    assert db.get_statistics()["total"] == 0
