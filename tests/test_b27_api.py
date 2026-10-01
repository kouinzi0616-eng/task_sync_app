"""B27: API の応答のカテゴリ（判定の理由・色の番号）と、環境変数で実物の設定を渡す流れ。

Render では環境変数 CATEGORY_CONFIG_JSON に設定（1行の JSON）を貼る。ここでは、実物に似せた
架空の設定（tests/fixtures/categories_reallike.json）を同じ形で渡して確かめる。名前・語はすべて架空。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import backend.api as api
from backend.task_sync import categories

ROOT = Path(__file__).resolve().parent.parent
REALLIKE_PATH = ROOT / "tests" / "fixtures" / "categories_reallike.json"


def _one_line(path: Path) -> str:
    return json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))


def test_parse_returns_category_hits_and_color(client, frozen_now):
    body = client.post("/api/parse", json={"text": "会議資料の準備 (3/15まで)"}).json()
    assert body["category"] == "仕事"
    assert body["category_hits"] == ["会議", "資料"]
    assert body["category_color"] == 1


def test_parse_default_category_has_no_hits(client, frozen_now):
    body = client.post("/api/parse", json={"text": "メモを書く"}).json()
    assert body["category"] == "暮らし"
    assert body["category_hits"] == []
    assert body["category_color"] == categories.sample_config().rule("暮らし").color


def test_batch_rows_have_hits_and_failed_rows_have_none(client, frozen_now, monkeypatch):
    def classify_or_fail(text):
        if "失敗させる行" in text:
            raise RuntimeError("内部の詳細-0000")
        return categories.classify(text)

    monkeypatch.setattr(api, "classify", classify_or_fail)
    body = client.post("/api/parse-batch", json={"tasks": ["英語の練習 (明日)", "失敗させる行"]}).json()
    assert [row["ok"] for row in body] == [True, False]
    assert (body[0]["category"], body[0]["category_hits"], body[0]["category_color"]) == ("学び", ["英語", "練習"], 3)
    assert (body[1]["category"], body[1]["category_hits"], body[1]["category_color"]) == (None, [], None)


def test_health_shows_which_config_without_names(client):
    body = client.get("/api/health").json()
    assert body["category_config"] == {"source": "sample", "categories": 4, "error": None}


def test_environment_variable_config_is_used_by_the_api(client, frozen_now, monkeypatch, reallike_categories):
    monkeypatch.setenv(categories.ENV_JSON, _one_line(REALLIKE_PATH))
    categories.reload_config(local_path=None)  # 環境変数を読む（Render では起動のとき）
    health = client.get("/api/health").json()["category_config"]
    assert health == {"source": "env", "categories": 4, "error": None}
    body = client.post("/api/parse", json={"text": "会議の議事録 (3/15まで)"}).json()
    assert body["category"] == reallike_categories.names[3]  # 団体1の除外語「議事録」→ 個人
    body = client.post("/api/parse", json={"text": "見本会の会議の議事録"}).json()
    assert (body["category"], body["category_hits"], body["category_color"]) == (
        reallike_categories.names[1], ["見本会", "会議"], 2)


def test_broken_environment_variable_keeps_the_app_working(client, frozen_now, monkeypatch, caplog):
    secret = "架空の秘密の名前"
    caplog.set_level(logging.ERROR, logger="task_sync")
    monkeypatch.setenv(categories.ENV_JSON, '{"default": "' + secret + '"')
    categories.reload_config(local_path=None)
    health = client.get("/api/health").json()["category_config"]
    assert health["source"] == "sample" and "JSON として読めません" in health["error"]
    assert secret not in json.dumps(health, ensure_ascii=False)
    assert "見本の設定を使います" in caplog.text and secret not in caplog.text
    assert client.post("/api/parse", json={"text": "英語の練習"}).json()["category"] == "学び"


def test_render_style_start_with_environment_variable(tmp_path):
    """Render と同じく、環境変数を付けて新しく起動すると、その設定で答える（別のプロセスで確かめる）"""
    code = textwrap.dedent(
        """
        import json
        import warnings

        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

        from backend.api import app

        with TestClient(app) as client:
            health = client.get("/api/health").json()["category_config"]
            body = client.post("/api/parse", json={"text": "副住職の法話 (明日)"}).json()
        print(json.dumps({"health": health, "category": body["category"], "hits": body["category_hits"],
                          "color": body["category_color"]}, ensure_ascii=False))
        """
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), categories.ENV_JSON: _one_line(REALLIKE_PATH)}
    env.pop(categories.ENV_FILE, None)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    reallike = categories.load_config_file(REALLIKE_PATH)
    assert out["health"] == {"source": "env", "categories": 4, "error": None}
    assert (out["category"], out["hits"], out["color"]) == (reallike.names[0], ["副住職", "法話"], 1)
    # 起動のログにもカテゴリ名は出さない（件数と読み先だけ）
    assert all(name not in result.stderr for name in reallike.names)
    assert "カテゴリの設定: env（4 個）" in result.stderr
