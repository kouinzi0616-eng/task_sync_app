"""公開したくない語（実名・寺院名・団体名・私用メールのドメイン・手元のパスなど）が、
リポジトリのファイルや履歴に残っていないかを、手元で数える（B27）。

語の一覧はリポジトリに入れない。private/ の下（.gitignore 済み）などに、1行1語のファイルを作って渡す
（# で始まる行と空の行は読み飛ばす）。

使い方（標準ライブラリと git だけで動く）:
    python scripts/find_words.py --words private/words.txt              # 今のファイル（git が管理しているもの）
    python scripts/find_words.py --words private/words.txt --history    # 履歴のすべての版と、コミットの作者・メッセージも
    python scripts/find_words.py --words private/words.txt backend frontend   # 場所を絞る

- 出力は「場所:行番号: 語の番号（words の何行目か）」だけで、語そのものや行の中身は出さない
  （画面の記録やログに残さないため）。
- ファイルの冒頭（30行目まで）の作者表記（「作成:」の行）は、既定では数えない
  （扱いは作者が決めるまで変えない約束のため）。数えるときは --include-author-lines を付ける。
- 全角・半角と大文字・小文字の違いはそろえて比べる（--history の版の中身は git grep で、大文字・小文字だけをそろえる）。
- ドメインらしい語（. を含み、英数字以外の文字がある語）は、メールなどに使われる英数字の形（punycode）も探す。
- 見つからなければ終了コード 0、見つかれば 1、使い方の誤りは 2。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTHOR_LINE = re.compile(r"作成\s*[:：]")
AUTHOR_LINE_LIMIT = 30  # 冒頭の何行目までを作者表記とみなすか


@dataclass(frozen=True)
class Hit:
    where: str  # ファイル（--history では 版:ファイル）か、コミットの項目
    line: int  # 行番号（コミットの項目は 0）
    word_no: int  # words の何番目の語か（1 始まり）


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def read_words(path: Path) -> list[str]:
    words = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        word = raw.strip()
        if word and not word.startswith("#"):
            words.append(word)
    return words


def search_forms(word: str) -> list[str]:
    """探す形（そろえた形と、ドメインなら punycode の形）"""
    forms = [normalize(word)]
    if "." in word and not word.isascii():
        try:
            forms.append(normalize(word).encode("idna").decode("ascii"))
        except UnicodeError:
            pass
    return list(dict.fromkeys(forms))


def _is_author_line(line: str, line_no: int) -> bool:
    return line_no <= AUTHOR_LINE_LIMIT and bool(AUTHOR_LINE.search(line))


def scan_line(where: str, line_no: int, line: str, words: list[str], include_author_lines: bool = False) -> list[Hit]:
    if not include_author_lines and _is_author_line(line, line_no):
        return []
    normalized = normalize(line)
    return [
        Hit(where, line_no, word_no)
        for word_no, word in enumerate(words, start=1)
        if any(form in normalized for form in search_forms(word))
    ]


def scan_text(where: str, text: str, words: list[str], include_author_lines: bool = False) -> list[Hit]:
    hits = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        hits += scan_line(where, line_no, line, words, include_author_lines)
    return hits


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode not in (0, 1):  # git grep は見つからないと 1
        raise RuntimeError(f"git {args[0]} が失敗しました")
    return result.stdout


def tracked_files(repo: Path, paths: list[str]) -> list[str]:
    return [name for name in _git(repo, "ls-files", "-z", "--", *paths).split("\0") if name]


def scan_files(repo: Path, words: list[str], paths: list[str], include_author_lines: bool = False) -> list[Hit]:
    hits = []
    for name in tracked_files(repo, paths):
        path = repo / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8000]:  # 画像などは飛ばす
            continue
        hits += scan_text(name, data.decode("utf-8", errors="replace"), words, include_author_lines)
    return hits


def scan_history(repo: Path, words: list[str], paths: list[str], include_author_lines: bool = False) -> list[Hit]:
    """履歴のすべての版の中身（git grep）と、コミットの作者・コミッター・メッセージ"""
    hits = []
    revisions = [rev for rev in _git(repo, "rev-list", "--all").split() if rev]
    patterns = []
    for word in words:
        patterns += search_forms(word)
    pattern_args = [arg for form in dict.fromkeys(patterns) for arg in ("-e", form)]
    seen: set[tuple[str, int, int]] = set()
    for rev in revisions:
        out = _git(repo, "grep", "-I", "-n", "-i", "-F", "--full-name", *pattern_args, rev, "--", *paths)
        for row in out.splitlines():
            # 形: <rev>:<path>:<line>:<中身>
            parts = row.split(":", 3)
            if len(parts) < 4:
                continue
            _, name, line_no, content = parts
            for hit in scan_line(f"{rev[:7]}:{name}", int(line_no), content, words, include_author_lines):
                key = (name, hit.line, hit.word_no)
                if key not in seen:  # 同じファイル・行・語は、最初に見つけた版だけを出す
                    seen.add(key)
                    hits.append(hit)
    fields = ("作者の名前", "作者のメール", "コミッターの名前", "コミッターのメール", "メッセージ")
    log = _git(repo, "log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e")
    for record in log.split("\x1e"):
        values = record.strip("\n").split("\0")
        if len(values) != 6:
            continue
        rev, *rest = values
        for field, value in zip(fields, rest, strict=True):
            for word_no, word in enumerate(words, start=1):
                if any(form in normalize(value) for form in search_forms(word)):
                    hits.append(Hit(f"コミット {rev[:7]} の{field}", 0, word_no))
    return hits


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="公開したくない語が残っていないかを数える（語そのものは出さない）")
    parser.add_argument("--words", required=True, type=Path, help="1行1語のファイル（リポジトリに入れない）")
    parser.add_argument("--history", action="store_true", help="履歴のすべての版とコミットの作者・メッセージも見る")
    parser.add_argument("--include-author-lines", action="store_true", help="冒頭の作者表記の行も数える")
    parser.add_argument("--repo", type=Path, default=ROOT, help="調べるリポジトリ（既定はこのリポジトリ）")
    parser.add_argument("paths", nargs="*", help="場所を絞る（既定は全部）")
    args = parser.parse_args(argv)
    try:
        words = read_words(args.words)
    except OSError:
        print("語のファイルを開けません", file=sys.stderr)
        return 2
    if not words:
        print("語のファイルに語がありません", file=sys.stderr)
        return 2

    hits = scan_files(args.repo, words, args.paths, args.include_author_lines)
    if args.history:
        hits += scan_history(args.repo, words, args.paths, args.include_author_lines)
    for hit in hits:
        line = f":{hit.line}" if hit.line else ""
        print(f"{hit.where}{line}: 語{hit.word_no}")
    scope = "今のファイルと履歴" if args.history else "今のファイル"
    note = "" if args.include_author_lines else "（冒頭の作者表記の行は数えていません）"
    print(f"{scope}: {len(words)} 語を調べ、{len(hits)} 件見つかりました{note}", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
