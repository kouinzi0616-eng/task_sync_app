"""B30: 同期ボタン（未実装の案内）を「カレンダー用ファイルを保存」に置きかえたこと。

- 画面: 前の同期ボタン・存在しない GOOGLE_CALENDAR_SETUP.md を案内する alert が無い。OAuth・Google の API を使わない
- API: POST /api/sync-calendar は本文を読まずに 501 を返す（カレンダーへの登録はサーバーでしない）
- 動き（.ics を保存する・UID は固定の ID・完了と期限なしは入れない）は tests/frontend/app_checks.mjs の「ics:」
データはすべて架空。外部には送信しない。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from backend import api

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
APP_CHECKS = ROOT / "tests" / "frontend" / "app_checks.mjs"
NODE = shutil.which("node")


def _without_comments(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(?m)(^|[^:\\])//.*$", r"\1", text)
    elif path.suffix == ".html":
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


def _screen_sources() -> dict[str, str]:
    """画面のファイルの中身（コメントは除く。説明のために前の名前を書くことはある）"""
    files = sorted(FRONTEND.glob("*.js")) + sorted(FRONTEND.glob("*.html")) + [FRONTEND / "manifest.json"]
    return {p.name: _without_comments(p) for p in files}


def test_old_sync_button_and_alert_are_gone():
    sources = _screen_sources()
    app = sources["app.js"]
    assert "GOOGLE_CALENDAR_SETUP" not in app
    assert not re.search(r"(?<![\w.])alert\s*\(", app)
    assert 'id="syncBtn"' not in sources["index.html"]
    assert 'id="icsBtn"' in sources["index.html"] and "カレンダー用ファイルを保存" in sources["index.html"]
    for name, text in sources.items():
        assert "Googleカレンダーに同期" not in text, name


def test_screen_has_no_oauth_or_google_api():
    for name, text in _screen_sources().items():
        lowered = text.lower()
        for word in ("oauth", "googleapis", "accounts.google", "gapi.", "client_id", "access_token"):
            assert word not in lowered, f"{name}: {word}"


def test_backend_web_app_does_not_import_calendar_client():
    source = (ROOT / "backend" / "api.py").read_text(encoding="utf-8")
    assert "calendar_client" not in source
    assert "task_sync.sync" not in source


def test_sync_calendar_returns_501_without_reading_the_body(client):
    for kwargs in ({"json": {"tasks": []}}, {"content": b"not json", "headers": {"Content-Type": "application/json"}}, {}):
        response = client.post("/api/sync-calendar", **kwargs)
        assert response.status_code == 501, kwargs
        body = response.json()
        assert body == {"status": "not_implemented", "detail": api.SYNC_CALENDAR_MESSAGE}
    assert "カレンダー用ファイルを保存" in api.SYNC_CALENDAR_MESSAGE


def test_ics_script_is_served_and_precached(client):
    response = client.get("/ics.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.content == (FRONTEND / "ics.js").read_bytes()
    sw = (FRONTEND / "sw.js").read_text(encoding="utf-8")
    assert "'/ics.js'" in sw


@pytest.mark.skipif(NODE is None, reason="node が無い（画面の動きの確認は飛ばす）")
def test_calendar_file_behaviour():
    result = subprocess.run([NODE, str(APP_CHECKS)], cwd=ROOT, env=dict(os.environ), capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    group = [r for r in json.loads(result.stdout) if r["name"].startswith("ics:")]
    assert len(group) >= 9, f"ics: の確認が {len(group)} 件しかありません"
    assert [f"{r['name']}: {r['detail']}" for r in group if not r["ok"]] == []
