"""B27: 画面のカテゴリの印（色の番号 1〜6）と、判定の理由の表示。

- 印の CSS のクラス名は中立な名前（badge-cat-0〜6）だけにする（カテゴリ名や団体名をクラス名にしない）
- 色の数は、サーバー（categories.COLOR_COUNT）・app.js・app.css でそろえる
- 動き（理由の表示・色の番号・文字のまま出すこと）は tests/frontend/app_checks.mjs の category: で確かめる
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.task_sync import categories

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
APP_JS = (FRONTEND / "app.js").read_text(encoding="utf-8")
APP_CSS = (FRONTEND / "app.css").read_text(encoding="utf-8")
NODE = shutil.which("node")

# 状態の印など、カテゴリ以外の印（中立な名前）
OTHER_BADGES = {"badge", "badge-review", "badge-overdue", "badge-lane", "badge-status", "badge-stale"}


def test_badge_classes_are_neutral_names_only():
    classes = set(re.findall(r"\.(badge(?:-[\w-]+)?)", APP_CSS))
    category_classes = {name for name in classes if name not in OTHER_BADGES}
    assert category_classes == {f"badge-cat-{n}" for n in range(categories.COLOR_COUNT + 1)}


def test_color_count_matches_between_server_and_screen():
    assert f"const CATEGORY_COLOR_COUNT = {categories.COLOR_COUNT};" in APP_JS


def test_screen_has_no_category_name_table():
    # 前は app.js にカテゴリ名 → クラス名の表があった。今は色の番号だけで選ぶ
    assert "CATEGORY_CLASSES" not in APP_JS
    assert "badge-${categoryClass}" not in APP_JS
    for name in categories.sample_config().names:
        assert name not in APP_JS, name


@pytest.mark.skipif(NODE is None, reason="node が無い（画面の動きの確認は飛ばす）")
def test_checks_catch_missing_reason(tmp_path):
    """検査そのものが働くことの確認: 理由を出さない app.js では category: が失敗する"""
    target = "if (task.category) item.appendChild(create('div', 'task-reason', categoryReason(task)));"
    assert target in APP_JS
    broken = tmp_path / "app_broken.js"
    broken.write_text(APP_JS.replace(target, ""), encoding="utf-8")
    result = subprocess.run(
        [NODE, str(ROOT / "tests" / "frontend" / "app_checks.mjs")],
        cwd=ROOT, env={**os.environ, "TSA_APP_JS": str(broken)},
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    failures = [r["name"] for r in json.loads(result.stdout) if r["name"].startswith("category:") and not r["ok"]]
    assert any("理由" in name for name in failures), failures
