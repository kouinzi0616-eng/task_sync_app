"""B28: 画面の JS（app.js）と Service Worker（sw.js）を node で動かして確かめる。

- tests/frontend/app_checks.mjs: 最小の偽 DOM（fake_dom.mjs）に index.html を読み込み、app.js を動かす
  （<img src=x onerror=...> を含む架空の応答を文字のまま出す・知らせの aria-live・タブの矢印キー・新しい版の案内）
- tests/frontend/sw_checks.mjs: 偽の self・caches・fetch の上で sw.js を動かす
  （画面はネット優先・控え・オフライン画面・SKIP_WAITING・古いキャッシュの削除）
本物のブラウザではないので、見た目・読み上げ・実際の Service Worker の登録は確かめられない。
node が無い環境では飛ばす（GitHub Actions の ubuntu-latest には入っている）。外部には送信しない。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_CHECKS = ROOT / "tests" / "frontend" / "app_checks.mjs"
SW_CHECKS = ROOT / "tests" / "frontend" / "sw_checks.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node が無い（画面の動きの確認は飛ばす）")


def _run(script: Path, **env_extra: str) -> list[dict]:
    result = subprocess.run(
        [NODE, str(script)],
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
    return _run(APP_CHECKS)


@pytest.fixture(scope="module")
def sw_results() -> list[dict]:
    return _run(SW_CHECKS)


def test_node_is_new_enough():
    version = subprocess.run([NODE, "--version"], capture_output=True, text=True, timeout=30).stdout
    assert int(version.strip().lstrip("v").split(".")[0]) >= 18, version


@pytest.mark.parametrize(
    ("prefix", "minimum"),
    [
        ("xss:", 10),  # HTML を混ぜた架空の応答を文字のまま出す
        ("notice:", 3),  # エラーは role=alert に出し、タイマーで消さない
        ("loading:", 5),  # 解析中の知らせ・aria-disabled
        ("error:", 4),  # 422・オフライン・500
        ("tabs:", 10),  # 矢印キー・Home・End・クリック
        ("update:", 8),  # 新しい版があります・SKIP_WAITING・読み込み直し
    ],
)
def test_app_behaviour(app_results, prefix, minimum):
    group = [r for r in app_results if r["name"].startswith(prefix)]
    assert len(group) >= minimum, f"{prefix} の確認が {len(group)} 件しかありません"
    assert _failures(group) == []


def test_app_checks_raised_no_exception(app_results):
    assert [r for r in app_results if "例外なしで動く" in r["name"]] == []
    assert _failures(app_results) == []


@pytest.mark.parametrize(
    ("prefix", "minimum"),
    [
        ("install:", 4),
        ("handlers:", 1),
        ("message:", 2),
        ("activate:", 3),
        ("navigate:", 2),
        ("app.js:", 1),
        ("offline:", 5),
        ("icon:", 1),
        ("scope:", 2),
        ("api:", 1),
    ],
)
def test_service_worker_behaviour(sw_results, prefix, minimum):
    group = [r for r in sw_results if r["name"].startswith(prefix)]
    assert len(group) >= minimum, f"{prefix} の確認が {len(group)} 件しかありません"
    assert _failures(group) == []


def test_sw_checks_raised_no_exception(sw_results):
    assert _failures(sw_results) == []


def test_checks_catch_inner_html_regression(tmp_path):
    """検査そのものが働くことの確認: 題名を innerHTML で入れる版の app.js は失敗になる"""
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "title.textContent = task.title;" in source
    broken = tmp_path / "app_broken.js"
    broken.write_text(source.replace("title.textContent = task.title;", "title.innerHTML = task.title;"), encoding="utf-8")
    failures = _failures(_run(APP_CHECKS, TSA_APP_JS=str(broken)), "xss:")
    assert any("HTML として解釈させる書き方を使わない" in f for f in failures), failures


def test_checks_catch_cache_first_regression(tmp_path):
    """検査そのものが働くことの確認: app.js などをキャッシュ優先に戻した sw.js は失敗になる"""
    source = (ROOT / "frontend" / "sw.js").read_text(encoding="utf-8")
    target = "event.respondWith(networkFirst(request, url.pathname));"
    assert target in source
    broken = tmp_path / "sw_broken.js"
    broken.write_text(source.replace(target, "event.respondWith(cacheFirst(request));"), encoding="utf-8")
    failures = _failures(_run(SW_CHECKS, TSA_SW_JS=str(broken)), "app.js:")
    assert failures, "キャッシュ優先に戻しても検査が通ってしまう"
