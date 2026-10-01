"""B29: 台帳の純粋関数（frontend/task_core.js）の検算を node:test で回す。

- 状態の移り変わり・2日以上動きなしの判定・台帳の形（Markdown の表・CSV）・Notion の CSV の読み取り・JSON の控え
- 検算そのものが働くことも確かめる（わざと壊した task_core.js では失敗する）
依存は増やさない（node の標準の node:test だけ）。node が無い環境では飛ばす。データはすべて架空。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "frontend" / "task_core.js"
TESTS = ROOT / "tests" / "frontend" / "task_core.test.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node が無い（純粋関数の検算は飛ばす）")


def _run(**env_extra: str) -> tuple[int, str]:
    result = subprocess.run(
        [NODE, "--test", str(TESTS)],
        cwd=ROOT,
        env={**os.environ, **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return result.returncode, result.stdout + result.stderr


def _count(output: str, word: str) -> int:
    match = re.search(rf"^# {word} (\d+)$", output, re.M)
    assert match, output[-2000:]
    return int(match.group(1))


def test_task_core_checks_pass():
    code, output = _run()
    assert code == 0, output[-4000:]
    assert _count(output, "fail") == 0
    assert _count(output, "pass") >= 29


@pytest.mark.parametrize(
    ("original", "broken", "expected_failure"),
    [
        ("const STALE_HOURS = 48;", "const STALE_HOURS = 24;", "isStale"),
        ("return /[\",\\r\\n]/.test(text)", "return /[\"\\r\\n]/.test(text)", "toCsv"),
        ("if (cell(row, '状態') !== STATUS_LABELS.my_turn) continue;", "", "readNotionCsv"),
        ("if (!changed) return task;", "", "transition"),
    ],
)
def test_checks_catch_broken_core(tmp_path, original, broken, expected_failure):
    """検算が働くことの確認: 規則を1つ壊した task_core.js では失敗する"""
    source = CORE.read_text(encoding="utf-8")
    assert original in source
    mutated = tmp_path / "task_core_broken.js"
    mutated.write_text(source.replace(original, broken), encoding="utf-8")
    code, output = _run(TSA_TASK_CORE=str(mutated))
    assert code != 0
    assert re.search(rf"^not ok \d+ - {expected_failure}", output, re.M), output[-3000:]
