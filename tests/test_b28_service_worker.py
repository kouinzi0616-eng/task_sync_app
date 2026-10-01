"""B28: Service Worker（sw.js）の版の上げ忘れと、更新・オフラインの決まり。

- 先にキャッシュするファイルの中身のハッシュを記録（tests/fixtures/sw_precache.json）と突き合わせ、
  中身が変わったのに CACHE_VERSION が同じなら失敗にする（scripts/sw_version.py）
- 画面の本体はネット優先・使っていない push の処理は無い・オフライン画面がある
動き（ネット優先・控え・オフライン画面・SKIP_WAITING）は test_b28_frontend_js.py で node を使って確かめる。
"""
from __future__ import annotations

import copy
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SW = (FRONTEND / "sw.js").read_text(encoding="utf-8")
APP_JS = (FRONTEND / "app.js").read_text(encoding="utf-8")


def _load_sw_version():
    spec = importlib.util.spec_from_file_location("tsa_sw_version", ROOT / "scripts" / "sw_version.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sw_version = _load_sw_version()
VERSION, PRECACHE = sw_version.read_sw(SW)


# ------------------------------------------------------------
# 版の上げ忘れ
# ------------------------------------------------------------

def test_cache_version_matches_the_record():
    errors = sw_version.problems(sw_version.current_state(), sw_version.load_record())
    assert errors == [], "\n".join(errors)


def test_record_lists_exactly_the_precached_files():
    record = sw_version.load_record()
    assert set(record["files"]) == set(PRECACHE)


def test_detects_changed_file_without_version_bump():
    state = sw_version.current_state()
    record = copy.deepcopy(state)
    record["files"]["/app.js"] = "0" * 64  # 前の版の app.js（架空のハッシュ）
    errors = sw_version.problems(state, record)
    assert len(errors) == 1
    assert "/app.js" in errors[0] and "上がっていません" in errors[0]


def test_detects_new_file_without_version_bump():
    state = sw_version.current_state()
    record = copy.deepcopy(state)
    del record["files"]["/offline.html"]
    assert "上がっていません" in sw_version.problems(state, record)[0]


def test_detects_bumped_version_with_stale_record():
    state = sw_version.current_state()
    record = copy.deepcopy(state)
    record["cache_version"] = state["cache_version"] - 1
    assert "--update" in sw_version.problems(state, record)[0]


def test_detects_version_going_down():
    state = sw_version.current_state()
    record = copy.deepcopy(state)
    record["cache_version"] = state["cache_version"] + 1
    assert "下げません" in sw_version.problems(state, record)[0]


def test_update_refuses_without_version_bump(tmp_path):
    path = tmp_path / "record.json"
    state = sw_version.current_state()
    assert sw_version.update(path, state) == []  # 初めての記録
    changed = copy.deepcopy(state)
    changed["files"]["/app.css"] = "f" * 64
    errors = sw_version.update(path, changed)
    assert errors and "上がっていません" in errors[0]
    assert sw_version.load_record(path) == state  # 書きかえていない
    changed["cache_version"] += 1
    assert sw_version.update(path, changed) == []
    assert sw_version.load_record(path) == changed


def test_hash_ignores_windows_line_endings(tmp_path):
    lf = tmp_path / "a.js"
    crlf = tmp_path / "b.js"
    lf.write_bytes(b"const a = 1;\nconst b = 2;\n")
    crlf.write_bytes(b"const a = 1;\r\nconst b = 2;\r\n")
    assert sw_version.file_hash(lf) == sw_version.file_hash(crlf)


def test_cache_name_uses_the_version():
    assert f"const CACHE_VERSION = {VERSION};" in SW
    assert "const CACHE_NAME = `${CACHE_PREFIX}v${CACHE_VERSION}`;" in SW
    assert "const CACHE_PREFIX = 'task-sync-';" in SW


# ------------------------------------------------------------
# 先にキャッシュするファイルが配信されていること
# ------------------------------------------------------------

@pytest.mark.parametrize("url", PRECACHE)
def test_precached_urls_are_served(client, url):
    response = client.get(url)
    assert response.status_code == 200, url
    path = sw_version.url_to_path(url)
    assert response.content == path.read_bytes(), url


def test_screen_files_are_network_first():
    match = re.search(r"const NETWORK_FIRST_PATHS = new Set\(\[(.*?)\]\);", SW, re.S)
    paths = set(re.findall(r"'([^']+)'", match.group(1)))
    assert {"/", "/index.html", "/app.js", "/app.css"} <= paths
    assert "request.mode === 'navigate'" in SW
    # もとの「キャッシュ優先」の書き方（caches.match を先に返す fetch 全体の処理）は残っていない
    assert "キャッシュファースト" not in SW


def test_offline_page_is_precached_and_served(client):
    assert "/offline.html" in PRECACHE
    assert "const OFFLINE_URL = '/offline.html';" in SW
    response = client.get("/offline.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "オフライン" in response.text
    assert '<link rel="stylesheet" href="/app.css">' in response.text
    assert "content-security-policy" in response.headers


def test_unused_push_handlers_are_removed():
    for word in ("'push'", "notificationclick", "showNotification", "openWindow"):
        assert word not in SW, word


def test_new_version_waits_for_the_user():
    # 入れてすぐには切り替えない。画面の「更新する」（SKIP_WAITING）で切り替える。
    # 例外は、案内を出せない古い版（v3 まで）からの移行だけ（動きは sw_checks.mjs で確かめる）
    assert SW.count("skipWaiting()") == 2
    assert "if (names.some(isLegacyCache)) return self.skipWaiting();" in SW
    assert "const FIRST_VERSION_WITH_UPDATE_NOTICE = 4;" in SW
    assert "event.data.type === 'SKIP_WAITING'" in SW
    assert "新しい版があります" in APP_JS
    assert "postMessage({ type: 'SKIP_WAITING' })" in APP_JS
    assert "controllerchange" in APP_JS


def test_index_has_update_banner_live_region():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '<div class="update-banner" id="updateBanner" role="status" aria-live="polite"></div>' in html
