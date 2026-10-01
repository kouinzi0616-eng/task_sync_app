"""B30: 画面が作るカレンダー用ファイル（.ics）を、別の実装（icalendar・開発用の依存）で読めるか確かめる。

- frontend/ics.js を node で動かして .ics を作り（tests/frontend/ics_cli.mjs）、Python の icalendar で読む
- RFC 5545 の決まり: 必須の項目・終日の予定（VALUE=DATE、DTEND は翌日）・75 オクテットの折り返し・CRLF
- UID はタスクの固定の ID（B29 の UUID）。期限を変えても変わらない
  （前のカレンダー同期の task_id は、期限や題名を変えると変わり、予定が二重に登録される）
node の検算（tests/frontend/ics.test.mjs）も pytest から回す。データはすべて架空。外部には送信しない。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ICS_JS = ROOT / "frontend" / "ics.js"
ICS_CLI = ROOT / "tests" / "frontend" / "ics_cli.mjs"
ICS_TESTS = ROOT / "tests" / "frontend" / "ics.test.mjs"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node が無い（.ics の確認は飛ばす）")

NOW = "2026-10-01T01:00:00.000Z"
ID1 = "11111111-1111-4111-8111-111111111111"
ID2 = "22222222-2222-4222-8222-222222222222"
ID3 = "33333333-3333-4333-8333-333333333333"
LONG_TITLE = "架空の長い題名、" + "とても長い説明;" * 15 + "🙏" + "\\終わり"


def _task(**overrides) -> dict:
    task = {
        "id": ID1, "title": "架空の資料作り", "lane": "仕事", "status": "my_turn", "next_action": "架空の下書きを読む",
        "deadline": "2026-10-15", "due_time": None, "category": "個人", "raw_text": "架空の資料作り (10/15まで)",
        "created_at": "2026-09-30T00:00:00.000Z", "updated_at": "2026-09-30T12:00:00.000Z", "revision": 0,
    }
    task.update(overrides)
    return task


def _build(tasks: list[dict], **env_extra: str) -> dict:
    result = subprocess.run(
        [NODE, str(ICS_CLI)],
        cwd=ROOT,
        input=json.dumps({"tasks": tasks, "now": NOW}),
        env={**os.environ, **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


SAMPLE_TASKS = [
    _task(),
    _task(id=ID2, title=LONG_TITLE, lane="学び, 読書", deadline="2026-12-31", next_action="1行目\n2行目", due_time="15:00",
          revision=3),
    _task(id=ID3, title="架空の期限なし", deadline=None),
]


@pytest.fixture(scope="module")
def built() -> dict:
    return _build(SAMPLE_TASKS)


@pytest.fixture(scope="module")
def calendar(built):
    icalendar = pytest.importorskip("icalendar", reason="requirements-dev.txt の icalendar が入っていない")
    return icalendar.Calendar.from_ical(built["text"])


@needs_node
def test_node_checks_pass():
    result = subprocess.run([NODE, "--test", str(ICS_TESTS)], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr
    assert re.search(r"^# fail 0$", result.stdout, re.M)
    assert int(re.search(r"^# pass (\d+)$", result.stdout, re.M).group(1)) >= 12


@needs_node
def test_icalendar_reads_the_file_without_errors(built, calendar):
    assert built["count"] == 2
    assert built["skipped"] == {"no_deadline": 1, "done": 0}
    assert calendar.errors == []
    assert str(calendar["VERSION"]) == "2.0"
    assert str(calendar["PRODID"]) == "-//task_sync_app//Task Sync//JA"
    events = calendar.walk("VEVENT")
    assert len(events) == 2
    for event in events:
        assert event.errors == []
        for name in ("UID", "DTSTAMP", "DTSTART", "DTEND", "SUMMARY"):
            assert name in event, name


@needs_node
def test_all_day_events_end_on_the_next_day(calendar):
    by_uid = {str(e["UID"]): e for e in calendar.walk("VEVENT")}
    assert set(by_uid) == {ID1, ID2}
    for uid, day in ((ID1, date(2026, 10, 15)), (ID2, date(2026, 12, 31))):
        event = by_uid[uid]
        start, end = event.decoded("DTSTART"), event.decoded("DTEND")
        assert type(start) is date and type(end) is date  # 時刻なし（VALUE=DATE）
        assert start == day
        assert end == day + timedelta(days=1)
        assert event["DTSTART"].params.get("VALUE") == "DATE"


@needs_node
def test_text_survives_folding_and_escaping(calendar):
    by_uid = {str(e["UID"]): e for e in calendar.walk("VEVENT")}
    event = by_uid[ID2]
    assert str(event["SUMMARY"]) == LONG_TITLE
    description = str(event["DESCRIPTION"])
    assert "次に本人がすること: 1行目\n2行目" in description
    assert "時刻: 15:00" in description
    assert event.decoded("DTSTAMP").isoformat() == "2026-10-01T01:00:00+00:00"
    assert int(event["SEQUENCE"]) == 3


@needs_node
def test_lines_are_folded_at_75_octets_with_crlf(built):
    raw = built["text"].encode("utf-8")
    assert raw.endswith(b"\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    lines = raw.split(b"\r\n")[:-1]
    assert max(len(line) for line in lines) <= 75
    assert any(line.startswith(b" ") for line in lines), "長い題名が折り返されていない"
    for line in lines:
        line.decode("utf-8")  # 文字の途中で切っていない（各行が UTF-8 として読める）


@needs_node
def test_uid_does_not_change_when_the_deadline_changes():
    before = _build([_task()])["text"]
    after = _build([_task(deadline="2026-11-30", title="架空の資料作り（改訂）", revision=1)])["text"]
    uid = re.compile(r"^UID:(.+)\r$", re.M)
    assert uid.findall(before) == uid.findall(after) == [ID1]
    assert "DTSTART;VALUE=DATE:20261015" in before and "DTSTART;VALUE=DATE:20261130" in after


def test_old_task_id_changes_when_the_deadline_changes():
    """前のカレンダー同期（calendar_client.py）の task_id は、カテゴリ・題名・期限日のハッシュ。
    期限を直すと別の値になり、前の予定が見つからずに二重に登録される（README の説明の裏づけ）"""
    from backend.task_sync.models import Task

    base = {"source_text": "架空の資料作り (10/15まで)", "title": "架空の資料作り", "category": "暮らし"}
    first = Task(due_date=date(2026, 10, 15), **base).task_id
    moved = Task(due_date=date(2026, 11, 30), **base).task_id
    renamed = Task(due_date=date(2026, 10, 15), **{**base, "title": "架空の資料作り（改訂）"}).task_id
    assert len({first, moved, renamed}) == 3


@needs_node
@pytest.mark.parametrize(
    ("original", "broken", "expected"),
    [
        ("const MAX_OCTETS = 75;", "const MAX_OCTETS = 80;", "折り返し"),
        ("`DTEND;VALUE=DATE:${formatDate(task.deadline, 1)}`", "`DTEND;VALUE=DATE:${formatDate(task.deadline)}`", "終日の予定"),
        (".replace(/,/g, '\\\\,')", "", "文字の逃がし方"),
    ],
)
def test_node_checks_catch_broken_ics(tmp_path, original, broken, expected):
    """検算が働くことの確認: 規則を1つ壊した ics.js では node の検算が失敗する"""
    source = ICS_JS.read_text(encoding="utf-8")
    assert original in source
    mutated = tmp_path / "ics_broken.js"
    mutated.write_text(source.replace(original, broken), encoding="utf-8")
    result = subprocess.run([NODE, "--test", str(ICS_TESTS)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                            env={**os.environ, "TSA_ICS_JS": str(mutated)}, timeout=120)
    assert result.returncode != 0
    assert re.search(rf"^not ok \d+ - {expected}", result.stdout, re.M), result.stdout[-3000:]
