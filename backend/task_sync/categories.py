"""
============================================================
categories.py — カテゴリ判定の正本（B27）
============================================================
タスクの文から、設定（JSON）に書いた判定語でカテゴリを決める。
画面・API（backend/api.py）も、カレンダー同期用の parser.py も、この関数を使う。

設定の読み先（上から順に、最初に見つかったもの）:
  1. 環境変数 CATEGORY_CONFIG_JSON … JSON の文字列そのもの（Render ではここに貼る）
  2. 環境変数 CATEGORY_CONFIG_FILE … JSON ファイルの場所
  3. private/categories.json      … 手元だけのファイル（.gitignore 済み）
  4. categories.sample.json        … 公開している見本（このファイルの隣）
読めない設定は使わず、見本に戻す（理由はログと /api/health に出す。設定の中身は出さない）。

決め方:
  - 判定語（keywords）と、カテゴリの名前（name・aliases）が文の中にあれば、1語につき1点。
    同じ場所で長い語の中に入っている短い語は数えない（「役員会」と「役員」が両方とも判定語でも、「役員会」は1点）。
  - 点がいちばん多いカテゴリにする。同点なら設定に書いた順で前のもの。
  - どれにも当たらなければ default のカテゴリ。
  - 語の境界: 1文字の語は、すぐ後ろに同じ種類の文字（漢字・ひらがな・カタカナ・英数字）が
    続くときは数えない（例: 「寺」は「寺田」では数えない）。英数字だけの語は、前後が英数字なら数えない。
  - 除外語（全体の exclude）: この語の中に出てきた判定語は数えない（例: 「共同声明」の中の「声明」）。
  - カテゴリの除外語（カテゴリの exclude）: この語が文にあれば、そのカテゴリは判定語では選ばない。
    ただし、そのカテゴリの名前（name・aliases）が書いてあるときは選べる。
  - 文字は NFKC（全角・半角の違いをそろえる）と小文字にしてから比べる。
============================================================
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("task_sync")

ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_CONFIG_PATH = Path(__file__).resolve().with_name("categories.sample.json")
LOCAL_CONFIG_PATH = ROOT / "private" / "categories.json"

ENV_JSON = "CATEGORY_CONFIG_JSON"
ENV_FILE = "CATEGORY_CONFIG_FILE"

# 色は画面の CSS（frontend/app.css の .badge-cat-1〜6）から選ぶ。色そのものは設定に書かない
# （文字と背景の対比 4.5:1 以上を、tests/test_b28_contrast.py で確かめた色だけを使うため）
COLOR_COUNT = 6
MAX_CATEGORIES = 12
MAX_NAME_LENGTH = 30  # 画面の端末保存（task_core.js の LIMITS.lane）と同じ
MAX_WORDS = 500  # 1つの設定に書ける語の合計
MAX_WORD_LENGTH = 40
MAX_CONFIG_BYTES = 64 * 1024

SOURCE_ENV = "env"
SOURCE_FILE = "file"
SOURCE_LOCAL = "local"
SOURCE_SAMPLE = "sample"
SOURCE_GIVEN = "given"  # テストなどで直接渡したもの

_TOP_KEYS = {"version", "default", "exclude", "categories"}
_CATEGORY_KEYS = {"name", "color", "keywords", "aliases", "exclude"}

_KANJI = r"㐀-䶿一-鿿豈-﫿々-〇"
_SCRIPT_CLASSES = (
    ("kanji", re.compile(f"[{_KANJI}]")),
    ("hiragana", re.compile(r"[ぁ-ゟ]")),
    ("katakana", re.compile(r"[゠-ヿ]")),
    ("alnum", re.compile(r"[0-9a-z]")),
)
_ALNUM_WORD = re.compile(r"[0-9a-z]+")


class CategoryConfigError(ValueError):
    """設定が読めない・形が違う。文言には設定の中身（カテゴリ名・語）を入れない"""


# ------------------------------------------------------------
# 設定の形
# ------------------------------------------------------------

@dataclass(frozen=True)
class CategoryRule:
    """1つのカテゴリ"""
    name: str
    color: int
    keywords: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()  # 名前のほかの書き方（ひらがな・略称など）
    exclude: tuple[str, ...] = ()  # この語が文にあれば、判定語ではこのカテゴリを選ばない

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class CategoryConfig:
    categories: tuple[CategoryRule, ...]
    default: str
    exclude: tuple[str, ...] = ()  # この語の中に出てきた判定語は数えない
    source: str = SOURCE_GIVEN

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(rule.name for rule in self.categories)

    def rule(self, name: str) -> CategoryRule:
        for rule in self.categories:
            if rule.name == name:
                return rule
        raise KeyError(name)


@dataclass(frozen=True)
class CategoryMatch:
    """判定の結果"""
    category: str
    color: int
    hits: tuple[str, ...] = ()  # 当たった語（文に出てきた順）。空なら default にした

    @property
    def is_default(self) -> bool:
        return not self.hits


# ------------------------------------------------------------
# 設定を読む
# ------------------------------------------------------------

def _word_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CategoryConfigError(f"{where} は文字列のリストにしてください")
    words: list[str] = []
    for index, word in enumerate(value, start=1):
        if not isinstance(word, str) or not word.strip():
            raise CategoryConfigError(f"{where} の {index} 番目が空か、文字列ではありません")
        word = word.strip()
        if len(word) > MAX_WORD_LENGTH:
            raise CategoryConfigError(f"{where} の {index} 番目が長すぎます（{MAX_WORD_LENGTH}文字まで）")
        if word not in words:
            words.append(word)
    return tuple(words)


def _check_keys(data: Mapping, allowed: set[str], where: str) -> None:
    # 「_」で始まる項目はメモとして読み飛ばす（例: "_note"）
    unknown = sorted(k for k in data if not (isinstance(k, str) and k.startswith("_")) and k not in allowed)
    if unknown:
        raise CategoryConfigError(f"{where} に知らない項目があります: {', '.join(map(str, unknown))}")


def parse_config(data: Mapping | str, source: str = SOURCE_GIVEN) -> CategoryConfig:
    """設定（dict か JSON の文字列）を確かめて CategoryConfig にする。形が違えば CategoryConfigError"""
    if isinstance(data, str):
        if len(data.encode("utf-8")) > MAX_CONFIG_BYTES:
            raise CategoryConfigError(f"設定が大きすぎます（{MAX_CONFIG_BYTES // 1024}KB まで）")
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            # 位置だけを伝える（中身は出さない）
            raise CategoryConfigError(f"JSON として読めません（{exc.lineno}行目 {exc.colno}文字目）") from None
    if not isinstance(data, Mapping):
        raise CategoryConfigError("設定のいちばん外側は { } にしてください")
    _check_keys(data, _TOP_KEYS, "設定")
    if data.get("version", 1) != 1:
        raise CategoryConfigError("version は 1 だけに対応しています")

    raw_categories = data.get("categories")
    if not isinstance(raw_categories, list) or not raw_categories:
        raise CategoryConfigError("categories に1つ以上のカテゴリを書いてください")
    if len(raw_categories) > MAX_CATEGORIES:
        raise CategoryConfigError(f"カテゴリは {MAX_CATEGORIES} 個までです")

    rules: list[CategoryRule] = []
    seen_names: set[str] = set()
    total_words = 0
    for index, raw in enumerate(raw_categories, start=1):
        where = f"categories の {index} 番目"
        if not isinstance(raw, Mapping):
            raise CategoryConfigError(f"{where} は {{ }} にしてください")
        _check_keys(raw, _CATEGORY_KEYS, where)
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CategoryConfigError(f"{where} に name（カテゴリ名）がありません")
        name = name.strip()
        if len(name) > MAX_NAME_LENGTH:
            raise CategoryConfigError(f"{where} の name が長すぎます（{MAX_NAME_LENGTH}文字まで）")
        if name in seen_names:
            raise CategoryConfigError(f"{where} の name が、前のカテゴリと同じです")
        seen_names.add(name)
        color = raw.get("color")
        if isinstance(color, bool) or not isinstance(color, int) or not 1 <= color <= COLOR_COUNT:
            raise CategoryConfigError(f"{where} の color は 1〜{COLOR_COUNT} の数にしてください")
        rule = CategoryRule(
            name=name,
            color=color,
            keywords=_word_list(raw.get("keywords"), f"{where} の keywords"),
            aliases=_word_list(raw.get("aliases"), f"{where} の aliases"),
            exclude=_word_list(raw.get("exclude"), f"{where} の exclude"),
        )
        total_words += len(rule.keywords) + len(rule.aliases) + len(rule.exclude)
        rules.append(rule)

    exclude = _word_list(data.get("exclude"), "exclude")
    total_words += len(exclude)
    if total_words > MAX_WORDS:
        raise CategoryConfigError(f"語が多すぎます（合わせて {MAX_WORDS} 語まで）")

    default = data.get("default")
    if not isinstance(default, str) or default.strip() not in seen_names:
        raise CategoryConfigError("default には、categories にあるカテゴリの name を書いてください")
    return CategoryConfig(categories=tuple(rules), default=default.strip(), exclude=exclude, source=source)


def load_config_file(path: Path | str, source: str = SOURCE_FILE) -> CategoryConfig:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise CategoryConfigError(f"設定ファイルが大きすぎます（{MAX_CONFIG_BYTES // 1024}KB まで）")
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        raise CategoryConfigError("設定ファイルを開けません") from None
    except UnicodeDecodeError:
        raise CategoryConfigError("設定ファイルが UTF-8 ではありません") from None
    return parse_config(text, source=source)


def sample_config() -> CategoryConfig:
    return load_config_file(SAMPLE_CONFIG_PATH, source=SOURCE_SAMPLE)


@dataclass(frozen=True)
class ConfigStatus:
    """どの設定を使っているか（/api/health に出す。カテゴリ名や語は入れない）"""
    source: str
    categories: int
    error: Optional[str] = None  # 読めなかった設定があったとき、その理由（見本に戻した）

    def as_dict(self) -> dict:
        return {"source": self.source, "categories": self.categories, "error": self.error}


def load_config(
    environ: Optional[Mapping[str, str]] = None,
    local_path: Optional[Path] = LOCAL_CONFIG_PATH,
) -> tuple[CategoryConfig, ConfigStatus]:
    """読み先の順に設定を探して読む。読めなければ見本に戻す（例外にしない）"""
    env = os.environ if environ is None else environ
    attempt: Optional[tuple[str, str]] = None  # (読み先の名前, 説明)
    try:
        if env.get(ENV_JSON, "").strip():
            attempt = (SOURCE_ENV, f"環境変数 {ENV_JSON}")
            config = parse_config(env[ENV_JSON], source=SOURCE_ENV)
        elif env.get(ENV_FILE, "").strip():
            attempt = (SOURCE_FILE, f"環境変数 {ENV_FILE} のファイル")
            config = load_config_file(env[ENV_FILE].strip(), source=SOURCE_FILE)
        elif local_path is not None and Path(local_path).is_file():
            attempt = (SOURCE_LOCAL, "private/categories.json")
            config = load_config_file(local_path, source=SOURCE_LOCAL)
        else:
            config = sample_config()
        return config, ConfigStatus(config.source, len(config.categories))
    except CategoryConfigError as exc:
        if attempt is None:  # 見本そのものが読めない（リポジトリが壊れている）
            raise
        reason = f"{attempt[1]}を使えません: {exc}"
        logger.error("カテゴリの設定: %s。見本の設定を使います", reason)
        config = sample_config()
        return config, ConfigStatus(config.source, len(config.categories), error=reason)


_active: Optional[tuple[CategoryConfig, ConfigStatus]] = None


def reload_config(
    environ: Optional[Mapping[str, str]] = None,
    local_path: Optional[Path] = LOCAL_CONFIG_PATH,
) -> CategoryConfig:
    """設定を読み直して、これから使う設定にする"""
    global _active
    _active = load_config(environ, local_path)
    return _active[0]


def set_active_config(config: CategoryConfig) -> None:
    """設定を直接入れる（テスト用）"""
    global _active
    _active = (config, ConfigStatus(config.source, len(config.categories)))


def active_config() -> CategoryConfig:
    if _active is None:
        reload_config()
    assert _active is not None
    return _active[0]


def config_status() -> ConfigStatus:
    active_config()
    assert _active is not None
    return _active[1]


# ------------------------------------------------------------
# 判定
# ------------------------------------------------------------

def normalize(text: str) -> str:
    """比べる前に文字をそろえる（全角英数→半角・半角カナ→全角・小文字）"""
    return unicodedata.normalize("NFKC", text).lower()


def _script(ch: str) -> Optional[str]:
    for name, pattern in _SCRIPT_CLASSES:
        if pattern.match(ch):
            return name
    return None


def _boundary_ok(text: str, start: int, end: int, word: str) -> bool:
    """語の境界: 1文字の語は後ろに同じ種類の文字が続けば×。英数字の語は前後が英数字なら×"""
    if _ALNUM_WORD.fullmatch(word):
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        return not (before and _script(before) == "alnum") and not (after and _script(after) == "alnum")
    if len(word) == 1 and end < len(text):
        kind = _script(word)
        return kind is None or _script(text[end]) != kind
    return True


def _masked_spans(text: str, words: tuple[str, ...]) -> list[bool]:
    masked = [False] * len(text)
    for word in words:
        needle = normalize(word)
        start = text.find(needle)
        while start >= 0:
            for i in range(start, start + len(needle)):
                masked[i] = True
            start = text.find(needle, start + 1)
    return masked


def _first_position(text: str, word: str, masked: list[bool]) -> int:
    """語が（境界と除外語を守って）最初に出てくる位置。無ければ -1"""
    needle = normalize(word)
    if not needle:
        return -1
    start = text.find(needle)
    while start >= 0:
        end = start + len(needle)
        if not any(masked[start:end]) and _boundary_ok(text, start, end, needle):
            return start
        start = text.find(needle, start + 1)
    return -1


def _hits(text: str, words: tuple[str, ...], masked: list[bool]) -> list[tuple[int, int, str]]:
    """当たった語の (始まり, 終わり, 語)。同じ場所の短い語（「役員会」の中の「役員」など）は数えない"""
    found = []
    for word in words:
        position = _first_position(text, word, masked)
        if position >= 0:
            found.append((position, position + len(normalize(word)), word))
    # 始まりが前・長いものから見て、すでに数えた語の中に入っている語は落とす
    found.sort(key=lambda hit: (hit[0], hit[0] - hit[1]))
    kept: list[tuple[int, int, str]] = []
    for start, end, word in found:
        if not any(k_start <= start and end <= k_end for k_start, k_end, _ in kept):
            kept.append((start, end, word))
    return kept


def classify(text: str, config: Optional[CategoryConfig] = None) -> CategoryMatch:
    """文からカテゴリを決める。当たった語（hits）も返す"""
    config = config or active_config()
    normalized = normalize(text or "")
    masked = _masked_spans(normalized, config.exclude)
    unmasked = [False] * len(normalized)

    best: Optional[tuple[CategoryRule, list[tuple[int, int, str]]]] = None
    for rule in config.categories:
        words = rule.names + tuple(w for w in rule.keywords if w not in rule.names)
        hits = _hits(normalized, words, masked)
        if hits and rule.exclude:
            named = any(_first_position(normalized, name, masked) >= 0 for name in rule.names)
            if not named and any(_first_position(normalized, word, unmasked) >= 0 for word in rule.exclude):
                hits = []  # カテゴリの除外語がある（名前が書いてあれば選べる）
        if hits and (best is None or len(hits) > len(best[1])):
            best = (rule, hits)

    if best is None:
        default = config.rule(config.default)
        return CategoryMatch(category=default.name, color=default.color)
    rule, hits = best
    return CategoryMatch(category=rule.name, color=rule.color, hits=tuple(word for _, _, word in hits))


def classify_category(text: str, config: Optional[CategoryConfig] = None) -> str:
    """カテゴリ名だけが要るとき"""
    return classify(text, config).category
