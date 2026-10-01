"""B29・B30: 画面の JS が外部に送信しないことを、コードの検査で確かめる。

- 通信の書き方（fetch・XMLHttpRequest・WebSocket・sendBeacon など）の数を、B28 の時点（e5f2b4c）と同じに保つ
  - app.js: fetch は解析の /api/parse-batch の 1 か所だけ
  - sw.js: 自分のサイトへの fetch の 3 か所だけ（他のサイトへの通信には手を出さない）
  - 新しく足した JS（台帳の計算・保存場所・カレンダー用ファイル）: 0 か所
- 画面のファイルに、外部の URL（http:// や https://）を書かない
- 保存・書き出し・コピーは、ブラウザの中だけで行う（IndexedDB・Blob・クリップボード）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# 通信になりうる書き方
NETWORK_PATTERNS = {
    "fetch": re.compile(r"(?<![\w.])fetch\s*\("),
    "XMLHttpRequest": re.compile(r"\bXMLHttpRequest\b"),
    "WebSocket": re.compile(r"\bWebSocket\b"),
    "EventSource": re.compile(r"\bEventSource\b"),
    "sendBeacon": re.compile(r"\bsendBeacon\b"),
    "importScripts": re.compile(r"\bimportScripts\b"),
    "import()": re.compile(r"(?<![\w.])import\s*\("),
    "new Image": re.compile(r"\bnew\s+Image\b"),
    ".src への代入": re.compile(r"\.src\s*="),
    "RTCPeerConnection": re.compile(r"\bRTCPeerConnection\b"),
    "window.open": re.compile(r"\bwindow\.open\s*\("),
    "location への代入": re.compile(r"\blocation\s*(\.\s*(href|assign|replace)\b|=)"),
    "form の送信": re.compile(r"\.submit\s*\("),
    "registration.sync": re.compile(r"\.sync\s*\.\s*register\b"),
}

# B28 の時点（e5f2b4c）の数。ここから増やさない
EXPECTED = {
    "app.js": {"fetch": 1},
    "sw.js": {"fetch": 3},
}

JS_FILES = sorted(FRONTEND.glob("*.js"))


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)(^|[^:\\])//.*$", r"\1", source)


def network_uses(source: str) -> dict[str, int]:
    code = _strip_comments(source)
    counts = {name: len(pattern.findall(code)) for name, pattern in NETWORK_PATTERNS.items()}
    return {name: n for name, n in counts.items() if n}


def test_new_frontend_files_exist():
    names = {p.name for p in JS_FILES}
    assert {"app.js", "sw.js", "task_core.js", "store.js", "ics.js"} <= names


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_network_calls_did_not_increase(path):
    expected = EXPECTED.get(path.name, {})
    assert network_uses(path.read_text(encoding="utf-8")) == expected, (
        f"{path.name} の通信の書き方が B28 の時点から変わっています。外部への送信を足していないか確かめてください"
    )


def test_the_only_app_request_is_the_parse_api():
    code = _strip_comments((FRONTEND / "app.js").read_text(encoding="utf-8"))
    calls = re.findall(r"(?<![\w.])fetch\s*\(\s*`\$\{API_BASE\}([^`]*)`", code)
    assert calls == ["/api/parse-batch"]
    assert re.search(r"const API_BASE = '';", code), "API は同じサイト（相対パス）だけ"


@pytest.mark.parametrize(
    "path",
    sorted(FRONTEND.glob("*.js")) + sorted(FRONTEND.glob("*.html")) + [FRONTEND / "manifest.json"],
    ids=lambda p: p.name,
)
def test_no_external_urls_in_screen_files(path):
    text = _strip_comments(path.read_text(encoding="utf-8")) if path.suffix == ".js" else path.read_text(encoding="utf-8")
    assert not re.search(r"https?://", text), f"{path.name} に外部の URL があります"


def test_saving_uses_only_the_browser():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    store = (FRONTEND / "store.js").read_text(encoding="utf-8")
    assert "indexedDB" in store and ".open(DB_NAME, DB_VERSION)" in store
    assert "URL.createObjectURL(new Blob(" in app  # 書き出しはブラウザの中でファイルを作る
    assert "navigator.clipboard.writeText" in app  # 台帳の形のコピー


def test_checker_catches_added_network_calls():
    """検査そのものが働くことの確認（架空のコード片）"""
    assert network_uses("navigator.sendBeacon('/x', data);") == {"sendBeacon": 1}
    assert network_uses("await fetch('https://example.invalid/');") == {"fetch": 1}
    assert network_uses("const img = new Image(); img.src = url;") == {"new Image": 1, ".src への代入": 1}
    assert network_uses("// fetch('/x') はコメント\nconst a = 1;") == {}
    assert network_uses("cache.fetchAll(); obj.fetch2();") == {}
