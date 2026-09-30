"""起動と画面配信のスモークテスト（今の挙動の記録）。"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Task Sync API"


def test_root_serves_pwa_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text


def test_pwa_files_are_served(client):
    expected = {
        "/manifest.json": "application/json",
        "/sw.js": "application/javascript",
        "/icon-192.png": "image/png",
        "/icon-512.png": "image/png",
        "/apple-touch-icon.png": "image/png",
        "/favicon.ico": "image/x-icon",
        "/static/index.html": "text/html",
    }
    for path, content_type in expected.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith(content_type), path


def test_missing_icon_size_is_404(client):
    assert client.get("/icon-999.png").status_code == 404


def test_parse_endpoint_returns_200(client):
    response = client.post("/api/parse", json={"text": "メモを書く"})
    assert response.status_code == 200


def test_sync_calendar_is_not_implemented_yet(client):
    response = client.post("/api/sync-calendar", json={"tasks": []})
    assert response.status_code == 200
    assert response.json()["status"] == "not_implemented"


def test_app_starts_from_other_folder_without_google_libraries(tmp_path):
    """別のフォルダから起動しても画面が出る。Google の依存が無くても import できる。"""
    code = textwrap.dedent(
        """
        import sys
        import warnings

        # Google カレンダー用の依存が入っていない環境を再現する
        for name in ("google", "googleapiclient", "google_auth_oauthlib"):
            sys.modules[name] = None

        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

        from backend.api import app

        with TestClient(app) as client:
            assert client.get("/").status_code == 200
            assert client.post("/api/parse", json={"text": "メモ"}).status_code == 200
        print("ok")
        """
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
