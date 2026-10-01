"""B29: 端末に保存したタスクの画面（本人の番・一覧・書き出しと読み込み）。

動きは tests/frontend/app_checks.mjs（偽 DOM の上で app.js・task_core.js・store.js を動かす）で確かめる。
偽の環境には IndexedDB が無いので、保存は一時の保存になる。IndexedDB に残ることは実ブラウザで確かめる。
ここでは HTML の静的検査（画面の数・見出しのある入力欄・読み込む順）もする。データはすべて架空。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
INDEX = (FRONTEND / "index.html").read_text(encoding="utf-8")
APP_CHECKS = ROOT / "tests" / "frontend" / "app_checks.mjs"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node が無い（画面の動きの確認は飛ばす）")


def _run(**env_extra: str) -> list[dict]:
    result = subprocess.run(
        [NODE, str(APP_CHECKS)],
        cwd=ROOT,
        env={**os.environ, **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _failures(results: list[dict], prefix: str = "") -> list[str]:
    return [f"{r['name']}: {r['detail']}" for r in results if r["name"].startswith(prefix) and not r["ok"]]


@pytest.fixture(scope="module")
def app_results() -> list[dict]:
    return _run()


@needs_node
@pytest.mark.parametrize(
    ("prefix", "minimum"),
    [
        ("save:", 7),  # 解析の結果を保存・固定の UUID・重ねて保存しない
        ("mine:", 14),  # 本人の番にする・次にすること・完了にする・フォーカス
        ("io:", 12),  # JSON の書き出しと読み込み・削除
        ("stale:", 6),  # 2日以上動きなしの印
        ("copy:", 5),  # 台帳の形（Markdown の表・CSV）のコピー
        ("notion:", 8),  # Notion の CSV（本人の番だけ）
        ("lanes:", 7),  # レーン名の設定
        ("network:", 1),  # 通信は解析だけ
    ],
)
def test_saved_tasks_behaviour(app_results, prefix, minimum):
    group = [r for r in app_results if r["name"].startswith(prefix)]
    assert len(group) >= minimum, f"{prefix} の確認が {len(group)} 件しかありません"
    assert _failures(group) == []


@needs_node
@pytest.mark.parametrize(
    ("original", "broken", "prefix"),
    [
        # 2日以上動きなしの印を出さない
        ("if (stale) meta.appendChild(create('span', 'badge badge-stale', '2日以上動きなし'));", "", "stale:"),
        # 一度保存した行も、もう一度保存してしまう
        ("const rows = parsedTasks.filter(row => row.ok !== false && !row.savedId);",
         "const rows = parsedTasks.filter(row => row.ok !== false);", "save:"),
    ],
)
def test_checks_catch_regressions(tmp_path, original, broken, prefix):
    """検査そのものが働くことの確認: 規則を1つ壊した app.js では失敗する"""
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert original in source
    mutated = tmp_path / "app_broken.js"
    mutated.write_text(source.replace(original, broken), encoding="utf-8")
    assert _failures(_run(TSA_APP_JS=str(mutated)), prefix)


# ------------------------------------------------------------
# HTML の静的検査
# ------------------------------------------------------------

class _Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))


def _elements() -> list[tuple[str, dict]]:
    parser = _Elements()
    parser.feed(INDEX)
    return parser.items


def test_only_one_screen_was_added():
    # B28 までは 解析・履歴・統計 の3つ（履歴・統計は中身の無い画面だった）。
    # B29 は「本人の番」を1つ足し、履歴は端末に保存した「一覧」に置きかえ、統計は外した
    tabs = [attrs for tag, attrs in _elements() if attrs.get("role") == "tab"]
    assert [t["data-tab"] for t in tabs] == ["parse", "mine", "tasks"]
    assert len([1 for _, attrs in _elements() if attrs.get("role") == "tabpanel"]) == 3


def test_every_form_control_has_a_label():
    elements = _elements()
    labels = {attrs.get("for") for tag, attrs in elements if tag == "label"}
    controls = [attrs for tag, attrs in elements if tag in {"input", "select", "textarea"}]
    assert len(controls) >= 5
    for attrs in controls:
        assert attrs.get("id") in labels or attrs.get("aria-label"), attrs


def test_helper_scripts_load_before_app_js():
    scripts = re.findall(r'<script src="/([\w.]+)" defer></script>', INDEX)
    assert scripts.index("task_core.js") < scripts.index("app.js")
    assert scripts.index("store.js") < scripts.index("app.js")
    assert scripts.index("ics.js") < scripts.index("app.js")


def test_helper_scripts_are_served(client):
    for name in ("task_core.js", "store.js", "ics.js"):
        response = client.get(f"/{name}")
        assert response.status_code == 200, name
        assert response.headers["content-type"].startswith("application/javascript"), name
        assert response.headers["cache-control"] == "no-cache", name
        assert response.content == (FRONTEND / name).read_bytes(), name


def test_default_lanes_are_generic_samples():
    # 公開しているコードには見本のレーン名だけを置く（本当の名前は端末ごとの設定）
    core = (FRONTEND / "task_core.js").read_text(encoding="utf-8")
    assert "const DEFAULT_LANES = ['仕事', '学び', '暮らし'];" in core


def test_hidden_attribute_wins_over_display_rules():
    # .field（display: flex）の中の控えの欄に hidden を付けても見えていた（実ブラウザで見つけた）
    css = (FRONTEND / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}", css)
    assert re.search(r'<div class="field" id="copyFallback" hidden>', INDEX)
