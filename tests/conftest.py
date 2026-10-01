"""テスト共通の準備。

- client: 本物の FastAPI アプリに対する TestClient（外部には送信しない）
- freeze_jst: backend.date_parser の「今」を日本時間の任意の時刻に固定する
- frozen_now: 基準日を 2026-10-01（木）10:00 JST に固定する
- カテゴリの設定: どのテストも、公開している見本（categories.sample.json）で始める（自動）
- reallike_categories: 実物に似せた架空の設定（tests/fixtures/categories_reallike.json）に切り替える

テストで使う文字列はすべて架空のもの。
"""
from __future__ import annotations

import os
import warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# 手元の環境変数で結果が変わらないよう、アプリが読む変数を消してから backend.api を読む
for _name in ("ENABLE_API_DOCS", "CATEGORY_CONFIG_JSON", "CATEGORY_CONFIG_FILE"):
    os.environ.pop(_name, None)

ROOT = Path(__file__).resolve().parent.parent
JST = ZoneInfo("Asia/Tokyo")

# 期限計算の基準にする固定の「今」（木曜日）
FIXED_NOW = datetime(2026, 10, 1, 10, 0, tzinfo=JST)

# 実物に似せた架空のカテゴリの設定（名前・語はすべて架空。形は実物と同じ）
REALLIKE_CATEGORIES = ROOT / "tests" / "fixtures" / "categories_reallike.json"


@pytest.fixture(autouse=True)
def _sample_categories():
    """どのテストも見本の設定で始める（手元の private/categories.json や環境変数を読まない）"""
    from backend.task_sync import categories

    categories.reload_config(environ={}, local_path=None)
    yield
    categories.reload_config(environ={}, local_path=None)


@pytest.fixture
def reallike_categories():
    """実物に似せた架空の設定に切り替え、その設定を返す"""
    from backend.task_sync import categories

    config = categories.load_config_file(REALLIKE_CATEGORIES)
    categories.set_active_config(config)
    return config


@pytest.fixture
def client():
    with warnings.catch_warnings():
        # 依存ライブラリ側の非推奨警告はテストの判定に関係しないので黙らせる
        warnings.simplefilter("ignore", DeprecationWarning)
        from fastapi.testclient import TestClient

    from backend.api import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def freeze_jst(monkeypatch):
    """backend.date_parser が使う datetime.now() を固定する関数を返す。"""
    import backend.date_parser as date_parser

    def _freeze(fixed: datetime) -> datetime:
        if fixed.tzinfo is None:
            fixed = fixed.replace(tzinfo=JST)

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed.astimezone(JST).replace(tzinfo=None)
                return fixed.astimezone(tz)

        monkeypatch.setattr(date_parser, "datetime", _FrozenDatetime)
        return fixed

    return _freeze


@pytest.fixture
def frozen_now(freeze_jst):
    return freeze_jst(FIXED_NOW)
