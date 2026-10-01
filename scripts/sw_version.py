"""Service Worker の版（sw.js の CACHE_VERSION）の上げ忘れを見つける。

sw.js が先にキャッシュするファイル（PRECACHE_URLS）の中身のハッシュ（sha256）を、
記録 tests/fixtures/sw_precache.json と突き合わせる。

- ファイルの中身が変わったのに CACHE_VERSION が記録と同じ → 上げ忘れ
- CACHE_VERSION を上げたのに記録が古いまま → 記録の更新忘れ
- CACHE_VERSION が記録より小さい → 版を下げた

画面のファイル（index.html・app.js・app.css・offline.html・manifest.json・アイコン）を変えたら:
    1. frontend/sw.js の CACHE_VERSION を 1 つ上げる
    2. python scripts/sw_version.py --update   # 記録を作り直す（版を上げていなければ断る）

使い方:
    python scripts/sw_version.py            # 突き合わせだけ（問題があれば終了コード 1）
    python scripts/sw_version.py --update   # 記録を作り直す
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SW_PATH = FRONTEND / "sw.js"
RECORD_PATH = ROOT / "tests" / "fixtures" / "sw_precache.json"

# 改行を LF にそろえてからハッシュを取る（Windows で CRLF で取り出しても同じ値になるように）
TEXT_SUFFIXES = {".html", ".js", ".css", ".json", ".svg", ".txt"}


def read_sw(text: str | None = None) -> tuple[int, list[str]]:
    """sw.js から (CACHE_VERSION, PRECACHE_URLS) を読む"""
    if text is None:
        text = SW_PATH.read_text(encoding="utf-8")
    version = re.search(r"^const CACHE_VERSION = (\d+);", text, re.M)
    block = re.search(r"^const PRECACHE_URLS = \[(.*?)\];", text, re.M | re.S)
    if not version or not block:
        raise ValueError("sw.js に CACHE_VERSION か PRECACHE_URLS が見つかりません")
    urls = re.findall(r"'([^']+)'", block.group(1))
    return int(version.group(1)), urls


def url_to_path(url: str) -> Path:
    """配信の URL → frontend/ のファイル（/ は index.html）"""
    name = "index.html" if url == "/" else url.lstrip("/")
    if "/" in name or name.startswith("."):
        raise ValueError(f"frontend/ 直下のファイルだけを扱います: {url}")
    return FRONTEND / name


def file_hash(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def current_state() -> dict:
    version, urls = read_sw()
    return {
        "cache_version": version,
        "files": {url: file_hash(url_to_path(url)) for url in urls},
    }


def load_record(path: Path = RECORD_PATH) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def changed_files(state: dict, record: dict) -> list[str]:
    urls = set(state["files"]) | set(record["files"])
    return sorted(u for u in urls if state["files"].get(u) != record["files"].get(u))


def problems(state: dict, record: dict | None) -> list[str]:
    if record is None:
        return ["記録がありません。python scripts/sw_version.py --update で作ってください"]
    now, before = state["cache_version"], record["cache_version"]
    if now < before:
        return [f"CACHE_VERSION が記録（{before}）より小さい {now} になっています。版は下げません"]
    if now == before:
        changed = changed_files(state, record)
        if changed:
            return [
                f"画面のファイル（{', '.join(changed)}）が変わったのに、frontend/sw.js の "
                f"CACHE_VERSION（{now}）が上がっていません。{now + 1} に上げてから "
                "python scripts/sw_version.py --update を実行してください"
            ]
        return []
    return [
        f"CACHE_VERSION を {before} → {now} に上げましたが、記録（tests/fixtures/sw_precache.json）が"
        "古いままです。python scripts/sw_version.py --update を実行してください"
    ]


def update(path: Path = RECORD_PATH, state: dict | None = None) -> list[str]:
    """記録を作り直す。版を上げずに中身だけ変わっているときは断って、理由を返す"""
    if state is None:
        state = current_state()
    record = load_record(path)
    if record is not None:
        if state["cache_version"] < record["cache_version"]:
            return problems(state, record)
        if state["cache_version"] == record["cache_version"] and changed_files(state, record):
            return problems(state, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return []


def main(argv: list[str]) -> int:
    if "--update" in argv:
        errors = update()
        if not errors:
            print(f"記録を更新しました: {RECORD_PATH.relative_to(ROOT)}")
    else:
        errors = problems(current_state(), load_record())
        if not errors:
            print("sw.js の版と画面のファイルは記録どおりです")
    for message in errors:
        print(message, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
