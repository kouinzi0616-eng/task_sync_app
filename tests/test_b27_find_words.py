"""B27: scripts/find_words.py（公開したくない語が残っていないかを手元で数える道具）の確認。

語はすべて架空。一時のフォルダに小さな git のリポジトリを作って確かめる（外部には送らない）。
出力には語そのものを出さないことも確かめる。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git が無い")


def _load():
    spec = importlib.util.spec_from_file_location("tsa_find_words", ROOT / "scripts" / "find_words.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


find_words = _load()

# 架空の語（実在しない名前・ドメイン）
WORDS = ["架空山見本寺", "見本太郎", "例示会", "架空見本.example", "C:\\Users\\someone"]


def _git(repo: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**os.environ, **(env or {})})


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "架空の人")
    _git(repo, "config", "user.email", "someone@example.invalid")
    (repo / "app.py").write_text('"""\n見本\n作成: 見本太郎（架空山見本寺）\n"""\nNAME = "例示会"\n', encoding="utf-8")
    (repo / "readme.md").write_text("手元の場所は C:\\Users\\someone\\docs です\n", encoding="utf-8")
    (repo / "icon.bin").write_bytes(b"\x00\x01" + "例示会".encode() + b"\x00" * 10)  # 画像などは飛ばす
    _git(repo, "add", ".")
    # 作者のメールのドメインに、英数字以外の文字を含むドメイン（git には punycode で入れる）
    author = {"GIT_AUTHOR_EMAIL": "someone@" + "架空見本.example".encode("idna").decode()}
    _git(repo, "commit", "-q", "-m", "最初", env=author)
    # 次の版で名前を消す（履歴には残る）
    (repo / "app.py").write_text('"""\n見本\n作成: 見本太郎（架空山見本寺）\n"""\nNAME = "汎用"\n', encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "名前を消す")
    words = tmp_path / "words.txt"
    words.write_text("# 架空の語の一覧\n\n" + "\n".join(WORDS) + "\n", encoding="utf-8")
    return repo, words


def test_read_words_skips_comments_and_blank_lines(repo):
    _, words = repo
    assert find_words.read_words(words) == WORDS


def test_current_files_skip_author_lines_by_default(repo):
    repo_dir, _ = repo
    hits = find_words.scan_files(repo_dir, WORDS, [])
    assert [(h.where, h.line, h.word_no) for h in hits] == [("readme.md", 1, 5)]


def test_author_lines_are_counted_when_asked(repo):
    repo_dir, _ = repo
    hits = find_words.scan_files(repo_dir, WORDS, [], include_author_lines=True)
    assert sorted((h.where, h.line, h.word_no) for h in hits) == [("app.py", 3, 1), ("app.py", 3, 2), ("readme.md", 1, 5)]


def test_history_finds_removed_names_and_punycode_email(repo):
    repo_dir, _ = repo
    hits = find_words.scan_history(repo_dir, WORDS, [])
    found = {(h.where.split(":", 1)[-1] if h.line else h.where, h.line, h.word_no) for h in hits}
    assert ("app.py", 5, 3) in found  # 前の版にだけある「例示会」
    assert any(where.endswith("作者のメール") and no == 4 for where, _, no in found)  # punycode のドメイン
    assert not any(where == "app.py" and line == 3 for where, line, _ in found)  # 作者表記の行は数えない


def test_cli_prints_numbers_but_never_the_words(repo):
    repo_dir, words = repo
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "find_words.py"), "--words", str(words), "--repo", str(repo_dir), "--history"],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "語3" in output and "語5" in output
    for word in WORDS + ["架空見本.example".encode("idna").decode()]:
        assert word not in output
    assert "冒頭の作者表記の行は数えていません" in result.stderr


def test_cli_returns_zero_when_nothing_is_found(repo, tmp_path):
    repo_dir, _ = repo
    words = tmp_path / "none.txt"
    words.write_text("どこにも無い架空の語\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "find_words.py"), "--words", str(words), "--repo", str(repo_dir)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0
    assert "0 件" in result.stderr


def test_cli_rejects_missing_or_empty_word_file(tmp_path):
    script = str(ROOT / "scripts" / "find_words.py")
    missing = subprocess.run([sys.executable, script, "--words", str(tmp_path / "missing.txt")],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert missing.returncode == 2
    empty = tmp_path / "empty.txt"
    empty.write_text("# だけ\n", encoding="utf-8")
    result = subprocess.run([sys.executable, script, "--words", str(empty)],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 2
