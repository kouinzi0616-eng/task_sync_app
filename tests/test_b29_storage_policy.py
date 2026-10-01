"""B29: 保存の方針（docs/storage.md）どおり、サーバーがタスクを保存しないこと。

- 使われていなかった履歴保存（backend/database.py・SQLite）は削除した
- アプリを読み込んでも、解析しても、作業フォルダにファイル（task_sync.db など）を作らない
テストの文字列はすべて架空。外部には送信しない。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "storage.md"


def test_database_module_is_removed():
    assert not (ROOT / "backend" / "database.py").exists()
    assert importlib.util.find_spec("backend.database") is None


def test_backend_web_app_does_not_use_sqlite():
    # 画面と API（backend/ 直下）は保存しない。backend/task_sync/ はカレンダー同期用の部品で別扱い
    for path in sorted((ROOT / "backend").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in source, path.name
        assert "TaskDatabase" not in source, path.name


def test_app_creates_no_files_in_working_folder(tmp_path):
    """別のフォルダから起動して解析しても、そのフォルダに何も作らない（もとは task_sync.db を作っていた）"""
    code = textwrap.dedent(
        """
        import warnings
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
        from backend.api import app

        with TestClient(app) as client:
            assert client.get("/").status_code == 200
            assert client.post("/api/parse-batch", json={"tasks": ["架空の資料作り (3/15まで)"]}).status_code == 200
        print("ok")
        """
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_storage_policy_document_has_the_decision_and_sources():
    text = DOC.read_text(encoding="utf-8")
    for words in ("IndexedDB", "無状態", "JSON", "UUID", "未確認", "二次情報", "取得日 2026-10-01"):
        assert words in text, words
    # 比べた案の表（端末の中・サーバーのファイル・無料 Postgres・有料・外部サービス）
    for option in ("A. 端末の中", "B. Render のサーバーのファイル", "C. Render の無料 Postgres", "D. 有料", "E. 外部"):
        assert option in text, option
