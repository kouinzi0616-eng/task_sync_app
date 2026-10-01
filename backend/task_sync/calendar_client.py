"""
============================================================
calendar_client.py — Google Calendar API クライアント
============================================================
OAuth認証、イベントの検索・作成・更新を行う。
extendedProperties.private.task_id を用いた二重登録防止。

作成: Tech僧侶（江音寺 荻原龍光）
作成日: 2026-02-16
バージョン: 1.0
動作環境: Python 3.10+
必要ライブラリ: google-api-python-client, google-auth-oauthlib
============================================================

注意（B30）: Web アプリ（Render）からは使わない。カレンダーへは、画面が作る .ics ファイル
（frontend/ics.js）で入れる。理由（手元の PC 向けの OAuth・広すぎる権限・task_id のハッシュによる
予定の二重登録）は README の「カレンダー用ファイル（.ics）」に書いた。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .models import Task

logger = logging.getLogger("task_sync")

# ═══════════════════════════════════════════════════════════════
# 定数
# ═══════════════════════════════════════════════════════════════

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# upsert検索範囲（デフォルト）
DEFAULT_PAST_DAYS = 30       # 過去30日
DEFAULT_FUTURE_DAYS = 180    # 未来180日

# extendedProperties のキー名
EXT_PROP_KEY = "task_id"


# ═══════════════════════════════════════════════════════════════
# 認証
# ═══════════════════════════════════════════════════════════════

def authenticate(
    credentials_path: Path = Path("credentials.json"),
    token_path: Path = Path("token.json"),
) -> Credentials:
    """
    Google OAuth認証を行い、Credentialsを返す。

    初回はブラウザで認証フローを実行し、token.jsonに保存。
    2回目以降はtoken.jsonから読み込み、期限切れなら自動リフレッシュ。
    """
    creds: Optional[Credentials] = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("トークンをリフレッシュ中...")
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"認証情報ファイルが見つかりません: {credentials_path}\n"
                    "Google Cloud Console からダウンロードしてください。"
                )
            logger.info("ブラウザで認証フローを開始します...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # トークンを保存
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info("トークンを保存しました: %s", token_path)

    return creds


# ═══════════════════════════════════════════════════════════════
# カレンダークライアント
# ═══════════════════════════════════════════════════════════════

class GoogleCalendarClient:
    """Google Calendar API のラッパー"""

    def __init__(self, creds: Credentials, calendar_id: str = "primary") -> None:
        self.service = build("calendar", "v3", credentials=creds)
        self.calendar_id = calendar_id
        logger.info("Google Calendar クライアント初期化完了 (calendar=%s)", calendar_id)

    # ─── イベント検索 ───

    def find_events_by_task_id(
        self,
        task_id: str,
        time_min: Optional[date] = None,
        time_max: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """
        extendedProperties.private.task_id が一致するイベントを検索。
        """
        today = date.today()
        if time_min is None:
            time_min = today - timedelta(days=DEFAULT_PAST_DAYS)
        if time_max is None:
            time_max = today + timedelta(days=DEFAULT_FUTURE_DAYS)

        try:
            result = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=f"{time_min.isoformat()}T00:00:00+09:00",
                    timeMax=f"{time_max.isoformat()}T23:59:59+09:00",
                    privateExtendedProperty=f"{EXT_PROP_KEY}={task_id}",
                    singleEvents=True,
                    maxResults=10,
                )
                .execute()
            )
            items = result.get("items", [])
            logger.debug("task_id=%s の既存イベント: %d件", task_id, len(items))
            return items
        except HttpError as exc:
            logger.error("イベント検索エラー: %s", exc)
            raise

    # ─── イベント作成 ───

    def create_event(self, task: Task) -> dict[str, Any]:
        """タスクから終日イベントを作成する"""
        body = self._build_event_body(task)
        try:
            event = (
                self.service.events()
                .insert(calendarId=self.calendar_id, body=body)
                .execute()
            )
            logger.info("イベント作成: %s (id=%s)", task.title, event.get("id"))
            return event
        except HttpError as exc:
            logger.error("イベント作成エラー: %s — %s", task.title, exc)
            raise

    # ─── イベント更新 ───

    def update_event(self, event_id: str, task: Task) -> dict[str, Any]:
        """既存イベントをタスク情報で更新する"""
        body = self._build_event_body(task)
        try:
            event = (
                self.service.events()
                .update(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    body=body,
                )
                .execute()
            )
            logger.info("イベント更新: %s (id=%s)", task.title, event_id)
            return event
        except HttpError as exc:
            logger.error("イベント更新エラー: %s — %s", task.title, exc)
            raise

    # ─── イベントボディ構築 ───

    @staticmethod
    def _build_event_body(task: Task) -> dict[str, Any]:
        """Task → Google Calendar API のイベント辞書"""
        # 終日イベント: start.date = due_date, end.date = due_date + 1日
        end_date = task.due_date + timedelta(days=1)
        return {
            "summary": f"[{task.category}] {task.title}",
            "description": task.description_text,
            "start": {"date": task.due_date.isoformat()},
            "end": {"date": end_date.isoformat()},
            "extendedProperties": {
                "private": {EXT_PROP_KEY: task.task_id},
            },
        }
