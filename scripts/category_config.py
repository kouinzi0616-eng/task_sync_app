"""カテゴリの設定（JSON）を手元で確かめる・試す・Render に貼る形にする（B27）。

使い方（標準ライブラリだけで動く。リポジトリのいちばん上で実行する）:
    python scripts/category_config.py check private/categories.json          # 形を確かめ、数を出す
    python scripts/category_config.py try private/categories.json "会議の議事録" "英語の練習"   # 判定を試す
    python scripts/category_config.py env private/categories.json            # 1行の JSON（Render の環境変数に貼る形）

ファイルを省くと、今のアプリと同じ読み先（CATEGORY_CONFIG_JSON → CATEGORY_CONFIG_FILE →
private/categories.json → 見本）から読む。
check は数だけを出し、カテゴリ名や語は出さない（画面の記録に残さないため）。try と env は中身を出す。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.task_sync import categories  # noqa: E402


def _load(path: str | None) -> categories.CategoryConfig:
    if path:
        return categories.load_config_file(path)
    config, status = categories.load_config()
    if status.error:
        raise categories.CategoryConfigError(status.error)
    return config


def _as_dict(config: categories.CategoryConfig) -> dict:
    data: dict = {"version": 1, "default": config.default}
    if config.exclude:
        data["exclude"] = list(config.exclude)
    data["categories"] = []
    for rule in config.categories:
        entry: dict = {"name": rule.name, "color": rule.color, "keywords": list(rule.keywords)}
        if rule.aliases:
            entry["aliases"] = list(rule.aliases)
        if rule.exclude:
            entry["exclude"] = list(rule.exclude)
        data["categories"].append(entry)
    return data


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="カテゴリの設定を確かめる・試す・1行にする")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="形を確かめ、数を出す（名前や語は出さない）")
    check.add_argument("file", nargs="?")
    trial = sub.add_parser("try", help="文を判定してみる")
    trial.add_argument("file")
    trial.add_argument("texts", nargs="+")
    env = sub.add_parser("env", help="1行の JSON にする（Render の環境変数 CATEGORY_CONFIG_JSON に貼る）")
    env.add_argument("file", nargs="?")
    args = parser.parse_args(argv)

    try:
        config = _load(args.file)
    except categories.CategoryConfigError as exc:
        print(f"使えません: {exc}", file=sys.stderr)
        return 1

    if args.command == "check":
        words = sum(len(r.keywords) + len(r.aliases) + len(r.exclude) for r in config.categories) + len(config.exclude)
        colors = "・".join(str(r.color) for r in config.categories)
        print(f"使えます: カテゴリ {len(config.categories)} 個・語 {words} 語・色の番号 {colors}"
              f"（読み先: {config.source}）")
    elif args.command == "try":
        for text in args.texts:
            match = categories.classify(text, config)
            reason = "・".join(match.hits) if match.hits else "当てはまる語なし（決まりのカテゴリ）"
            print(f"{text} → {match.category}（色 {match.color}・理由: {reason}）")
    else:
        print(json.dumps(_as_dict(config), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
