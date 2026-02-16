"""
============================================================
sync.py — 同期オーケストレーター
============================================================
パースされたタスクリストをGoogle Calendarへupsertする。

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
============================================================
"""

from __future__ import annotations

import logging
from typing import Optional

from .calendar_client import GoogleCalendarClient
from .models import SyncAction, SyncResult, Task

logger = logging.getLogger("task_sync")


def sync_tasks(
    tasks: list[Task],
    client: GoogleCalendarClient,
    dry_run: bool = False,
) -> list[SyncResult]:
    """
    タスクリストをGoogle Calendarへ同期（upsert）する。

    Parameters
    ----------
    tasks : list[Task]
        同期対象タスク
    client : GoogleCalendarClient
        認証済みクライアント
    dry_run : bool
        Trueなら差分表示のみで実際の書き込みは行わない

    Returns
    -------
    list[SyncResult]
    """
    results: list[SyncResult] = []
    insert_count = 0
    update_count = 0
    error_count = 0

    for task in tasks:
        result = _upsert_one(task, client, dry_run)
        results.append(result)

        if result.error:
            error_count += 1
        elif result.action == SyncAction.INSERT:
            insert_count += 1
        elif result.action == SyncAction.UPDATE:
            update_count += 1

    # サマリーログ
    mode = "[DRY-RUN] " if dry_run else ""
    logger.info(
        "%s同期完了: 全%dタスク（INSERT=%d, UPDATE=%d, ERROR=%d）",
        mode, len(tasks), insert_count, update_count, error_count,
    )

    return results


def _upsert_one(
    task: Task,
    client: GoogleCalendarClient,
    dry_run: bool,
) -> SyncResult:
    """1タスク分のupsert処理"""
    try:
        existing = client.find_events_by_task_id(task.task_id)

        if existing:
            # 既存イベントがある → UPDATE
            event_id = existing[0]["id"]
            if dry_run:
                logger.info(
                    "[DRY-RUN] UPDATE: %s (task_id=%s, event_id=%s)",
                    task.title, task.task_id, event_id,
                )
                return SyncResult(
                    task=task, action=SyncAction.SKIP, calendar_event_id=event_id,
                )
            event = client.update_event(event_id, task)
            return SyncResult(
                task=task, action=SyncAction.UPDATE, calendar_event_id=event["id"],
            )
        else:
            # 新規 → INSERT
            if dry_run:
                logger.info(
                    "[DRY-RUN] INSERT: %s (task_id=%s)",
                    task.title, task.task_id,
                )
                return SyncResult(task=task, action=SyncAction.SKIP)
            event = client.create_event(task)
            return SyncResult(
                task=task, action=SyncAction.INSERT, calendar_event_id=event["id"],
            )

    except Exception as exc:
        logger.error("同期エラー: %s — %s", task.title, exc)
        return SyncResult(task=task, action=SyncAction.SKIP, error=str(exc))
