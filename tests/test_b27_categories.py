"""B27: カテゴリ判定の一本化（正本は backend/task_sync/categories.py）と、判定語の設定ファイル化。

確かめること:
- 見本の設定（公開している categories.sample.json）だけで動き、判定が期待どおり。
- 実物に似せた架空の設定（tests/fixtures/categories_reallike.json）で:
  - 前の画面・API の決め方（tests/b27_legacy.py で再現）と、同じ文では同じカテゴリになる（=今と同じ表示）
  - カレンダー同期用にだけあった語も効く
  - 部分一致の誤判定（「寺田さんに電話」「共同声明の確認」「会議の議事録」など）が直っている
- 語の境界・除外語・カテゴリの除外語・同じ場所の短い語・文字の正規化
- 設定の読み先の順（環境変数の JSON → 環境変数のファイル → private/categories.json → 見本）と、
  読めない設定は見本に戻すこと（ログと理由に、設定の中身を出さない）

名前・語はすべて架空。実物の設定はリポジトリに置かない（README の「カテゴリの設定」）。
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.task_sync import categories
from backend.task_sync.categories import CategoryConfigError, classify, parse_config

ROOT = Path(__file__).resolve().parent.parent
REALLIKE_PATH = ROOT / "tests" / "fixtures" / "categories_reallike.json"


def _load_legacy():
    spec = importlib.util.spec_from_file_location("b27_legacy", ROOT / "tests" / "b27_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


legacy = _load_legacy()

# ------------------------------------------------------------
# 実物に似せた架空の語の表（前のコードと同じ形: 画面・API 用と、カレンダー同期用の2つ）
# ------------------------------------------------------------
OTERA = "寺務（架空）"
GROUP1 = "見本会"
GROUP2 = "試作部"
PERSONAL = "個人"
ORDER = [OTERA, GROUP1, GROUP2, PERSONAL]  # 前の画面・API の同点の順

LEGACY_API = {
    OTERA: ["法要", "お経", "法事", "檀家", "お寺", "寺院", "本堂", "境内", "供養", "住職", "参拝", "盆", "彼岸"],
    GROUP1: ["見本会", "みほんかい", "ミホンカイ", "会議", "総会", "役員", "会報", "行事"],
    GROUP2: ["試作部", "しさくぶ", "シサクブ", "御詠歌", "和歌", "短歌", "稽古", "練習", "発表会"],
    PERSONAL: ["買い物", "病院", "歯医者", "旅行", "予約", "家族", "趣味", "個人的"],
}
LEGACY_CALENDAR = {
    GROUP1: ["見本会", "みほんかい", "見本", "会報", "役員会"],
    GROUP2: ["試作部", "しさくぶ", "試作", "和讃", "声明", "御詠歌"],
    OTERA: ["寺", "法要", "檀家", "本堂", "お盆", "彼岸", "施餓鬼", "山門", "法話", "総代", "副住職"],
}
REALLIKE_TABLES = {
    "api_keywords": LEGACY_API,
    "calendar_keywords": LEGACY_CALENDAR,
    "order": ORDER,
    "colors": {OTERA: 1, GROUP1: 2, GROUP2: 3, PERSONAL: 4},  # 前の CSS の4色と同じ番号
    "default": PERSONAL,
    "group_names": [GROUP1, GROUP2],
    "category_exclude": {GROUP1: ["議事録"]},
    "exclude": ["共同声明", "声明文", "国会議", "和歌山"],
}


def legacy_display(text: str) -> str:
    return legacy.legacy_classify(text, LEGACY_API, ORDER, PERSONAL)


@pytest.fixture(scope="module")
def sample():
    return categories.sample_config()


@pytest.fixture(scope="module")
def reallike():
    return categories.load_config_file(REALLIKE_PATH)


# ------------------------------------------------------------
# 見本の設定（公開しているもの）
# ------------------------------------------------------------

def test_sample_is_the_default_and_has_only_generic_names(sample):
    assert categories.active_config().source == categories.SOURCE_SAMPLE
    assert sample.names == ("仕事", "学び", "地域", "暮らし")
    assert sample.default == "暮らし"
    assert categories.config_status().as_dict() == {"source": "sample", "categories": 4, "error": None}


@pytest.mark.parametrize(
    ("text", "category", "hits"),
    [
        ("会議資料の準備 (3/15まで)", "仕事", ("会議", "資料")),
        ("架空の取引先にメール返信", "仕事", ("取引先", "メール返信")),
        ("英語の練習", "学び", ("英語", "練習")),
        ("町内会の総会", "地域", ("町内会", "総会")),
        ("回覧板を回す", "地域", ("回覧板",)),
        ("病院の予約 (至急)", "暮らし", ("病院", "予約")),
        ("仕事の電話", "仕事", ("仕事",)),  # カテゴリ名そのものも数える
        ("メモを書く", "暮らし", ()),  # どれにも当たらない → 既定
        ("国会議員の資料を読む", "仕事", ("資料",)),  # 「国会議」の中の「会議」は数えない
        ("国会議員に連絡", "暮らし", ()),
        ("株主総会の案内", "暮らし", ()),  # 地域の除外語「株主総会」
    ],
)
def test_sample_classification(sample, text, category, hits):
    match = classify(text, sample)
    assert (match.category, match.hits) == (category, hits)
    assert match.color == sample.rule(category).color
    assert match.is_default is (hits == ())


def test_sample_category_exclude_wins_over_keywords_without_the_name(sample):
    # 地域の除外語（株主総会）があれば、地域の判定語（町内会・総会）では地域にしない。名前「地域」があれば地域
    assert classify("町内会で株主総会の話", sample).category == "暮らし"
    assert classify("地域の町内会で株主総会の話", sample).category == "地域"


# ------------------------------------------------------------
# 実物に似せた架空の設定: 前と同じ表示になること
# ------------------------------------------------------------

def test_reallike_fixture_is_made_by_the_same_conversion_as_the_real_config(reallike):
    # 実物の設定も、同じ legacy_to_config で（手元で）作った。架空の表から作ると、置いてある設定と一致する
    expected = legacy.legacy_to_config(**REALLIKE_TABLES)
    stored = json.loads(REALLIKE_PATH.read_text(encoding="utf-8"))
    assert {key: value for key, value in stored.items() if not key.startswith("_")} == expected
    assert reallike.names == tuple(ORDER)
    assert reallike.default == PERSONAL
    assert [rule.color for rule in reallike.categories] == [1, 2, 3, 4]
    assert reallike.rule(GROUP1).aliases == ("みほんかい", "ミホンカイ", "見本")
    assert reallike.rule(GROUP2).aliases == ("しさくぶ", "シサクブ", "試作")


def test_reallike_as_environment_variable_is_read_the_same(reallike):
    # Render の環境変数には1行の JSON を貼る。ファイルで読んだときと同じ設定になる
    one_line = json.dumps(json.loads(REALLIKE_PATH.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
    config, status = categories.load_config({categories.ENV_JSON: one_line}, local_path=None)
    assert status.source == "env" and status.error is None
    assert config.categories == reallike.categories
    assert config.default == reallike.default and config.exclude == reallike.exclude


API_WORDS = [word for name in ORDER for word in LEGACY_API[name]]
TEMPLATES = ["{w}", "{w}の準備", "明日の{w}", "{w}について連絡"]
CORPUS_SAME = list(dict.fromkeys(
    [t.format(w=w) for w in API_WORDS for t in TEMPLATES]
    + [f"{a}と{b}" for a, b in itertools.permutations(API_WORDS, 2)]
))


def test_reallike_gives_the_same_category_as_before_for_every_old_word_and_pair(reallike):
    """前の画面・API の語だけでできた文（1語・2語の組み合わせ全部）は、前と同じカテゴリになる"""
    assert len(CORPUS_SAME) > 1500
    different = [(text, legacy_display(text), classify(text, reallike).category)
                 for text in CORPUS_SAME if classify(text, reallike).category != legacy_display(text)]
    assert different == []


def test_legacy_reference_matches_the_old_rules():
    # 再現した前の決め方そのものの確認（同点は順番・大文字小文字を区別しない・当たらなければ既定）
    assert legacy_display("法要と会議") == OTERA  # 1点ずつの同点 → 前の順
    assert legacy_display("見本会の会議") == GROUP1
    assert legacy_display("寺田さんに電話") == PERSONAL  # 画面・API の表には「寺」が無かった
    assert legacy_display("会議の議事録") == GROUP1  # 前は団体になっていた（誤判定）
    assert legacy_display("和歌山へ旅行") == GROUP2  # 「和歌」と「旅行」の同点 → 前の順（誤判定）


CALENDAR_ONLY = {w: name for name, words in LEGACY_CALENDAR.items() for w in words if w not in API_WORDS}


@pytest.mark.parametrize(("word", "category"), sorted(CALENDAR_ONLY.items()))
def test_reallike_also_uses_words_that_were_only_in_the_calendar_side(reallike, word, category):
    for template in TEMPLATES:
        assert classify(template.format(w=word), reallike).category == category


@pytest.mark.parametrize(
    ("text", "category", "hits"),
    [
        # 前のコード（名前は実物）の例を、架空の設定で同じ形にしたもの
        ("会議資料の準備 (3/15まで)", GROUP1, ("会議",)),
        ("法要の準備 (3/15まで)", OTERA, ("法要",)),
        ("御詠歌の稽古 (5月中)", GROUP2, ("御詠歌", "稽古")),
        ("本堂の掃除 (早め)", OTERA, ("本堂",)),
        ("病院の予約 (至急)", PERSONAL, ("病院", "予約")),
        ("買い物 (来週まで)", PERSONAL, ("買い物",)),
        ("メモを書く", PERSONAL, ()),
        ("見本会の会議資料", GROUP1, ("見本会", "会議")),  # 名前の略称「見本」は「見本会」の中なので数えない
        ("副住職の法話", OTERA, ("副住職", "法話")),  # 「副住職」の中の「住職」は数えない
    ],
)
def test_reallike_examples(reallike, text, category, hits):
    match = classify(text, reallike)
    assert (match.category, match.hits) == (category, hits)


@pytest.mark.parametrize(
    ("text", "category", "why"),
    [
        ("寺田さんに電話", PERSONAL, "1文字の「寺」は、後ろに漢字が続く「寺田」では数えない"),
        ("寺島さんの資料", PERSONAL, "同じ"),
        ("共同声明の確認", PERSONAL, "除外語「共同声明」の中の「声明」は数えない"),
        ("声明文を読む", PERSONAL, "除外語「声明文」"),
        ("会議の議事録", PERSONAL, "団体1の除外語「議事録」があるので、判定語「会議」では団体1にしない"),
        ("見本会の会議の議事録", GROUP1, "名前「見本会」が書いてあれば、除外語があっても団体1"),
        ("盆栽の手入れ", PERSONAL, "1文字の「盆」は「盆栽」では数えない"),
        ("和歌山へ旅行", PERSONAL, "除外語「和歌山」の中の「和歌」は数えない（旅行で個人）"),
        ("国会議員に連絡", PERSONAL, "除外語「国会議」の中の「会議」は数えない"),
        ("お盆の準備", OTERA, "「お盆」"),
        ("寺の掃除", OTERA, "「寺」の後ろが「の」なら数える"),
        ("架空寺の行事と法要", OTERA, "「○○寺」も数える（前の文字は見ない）"),
        ("声明の稽古", GROUP2, "除外語の外の「声明」は数える"),
    ],
)
def test_reallike_partial_match_regressions(reallike, text, category, why):
    assert classify(text, reallike).category == category, why


def test_regressions_were_wrong_with_the_old_calendar_side():
    # 前のカレンダー同期用（先に当たったものを採る・部分一致）では誤判定だったことの記録
    def old_calendar(text):
        for name in (GROUP1, GROUP2, OTERA):
            if any(word in text for word in LEGACY_CALENDAR[name]):
                return name
        return PERSONAL

    assert old_calendar("寺田さんに電話") == OTERA
    assert old_calendar("共同声明の確認") == GROUP2


# ------------------------------------------------------------
# 決め方の細かい規則
# ------------------------------------------------------------

def _config(**overrides):
    data = {
        "version": 1,
        "default": "その他",
        "categories": [
            {"name": "甲", "color": 1, "keywords": ["abc", "寺", "テ", "長い語", "長い"]},
            {"name": "乙", "color": 2, "keywords": ["点検"]},
            {"name": "その他", "color": 6, "keywords": []},
        ],
    }
    data.update(overrides)
    return parse_config(data)


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("abc の件", "甲"),
        ("xabc の件", "その他"),  # 英数字の語は、前後が英数字なら数えない
        ("abc1 の件", "その他"),
        ("ＡＢＣ の件", "甲"),  # 全角・大文字も NFKC と小文字でそろえる
        ("テの字", "甲"),
        ("テスト", "その他"),  # 1文字のカタカナも、後ろにカタカナが続けば数えない
        ("ﾃの字", "甲"),  # 半角カナ
    ],
)
def test_boundaries_and_normalization(text, category):
    assert classify(text, _config()).category == category


def test_tie_goes_to_the_earlier_category_and_more_hits_win():
    config = _config()
    assert classify("寺の点検", config).category == "甲"  # 1点ずつ → 前の「甲」
    assert classify("寺の点検と点検", config).hits == ("寺",)
    config2 = _config(categories=[
        {"name": "甲", "color": 1, "keywords": ["寺"]},
        {"name": "乙", "color": 2, "keywords": ["点検", "掃除"]},
        {"name": "その他", "color": 6},
    ])
    assert classify("寺の点検と掃除", config2).category == "乙"


def test_shorter_word_inside_a_longer_hit_counts_once():
    match = classify("長い語を書く", _config())
    assert match.hits == ("長い語",)


def test_hits_are_in_the_order_they_appear():
    config = _config(categories=[
        {"name": "甲", "color": 1, "keywords": ["後", "先"]},
        {"name": "その他", "color": 6},
    ])
    assert classify("先にやって後で見る", config).hits == ("先", "後")


def test_global_exclude_masks_only_inside_the_word():
    config = _config(exclude=["点検表"])
    assert classify("点検表を印刷", config).category == "その他"
    assert classify("点検表と点検", config).category == "乙"


def test_classify_handles_empty_text(sample):
    assert classify("", sample).category == sample.default
    assert classify(None, sample).category == sample.default  # type: ignore[arg-type]


# ------------------------------------------------------------
# 設定の形の確かめ（理由の文言に、設定の中身を入れない）
# ------------------------------------------------------------

SECRET = "架空の秘密の名前"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ("{", "JSON として読めません"),
        ("[]", "いちばん外側"),
        ({"default": "x", "categories": []}, "1つ以上"),
        ({"default": SECRET, "categories": [{"name": "甲", "color": 1}]}, "default には"),
        ({"default": "甲", "categories": [{"name": "甲", "color": 7}]}, "color は 1〜6"),
        ({"default": "甲", "categories": [{"name": "甲", "color": True}]}, "color は 1〜6"),
        ({"default": "甲", "categories": [{"name": "甲", "color": 1}, {"name": "甲", "color": 2}]}, "同じです"),
        ({"default": "甲", "categories": [{"name": "甲", "color": 1, "keywords": "語"}]}, "リストにして"),
        ({"default": "甲", "categories": [{"name": "甲", "color": 1, "keywords": [""]}]}, "空か"),
        ({"default": "甲", "categories": [{"name": "甲", "color": 1, "keyword": ["語"]}]}, "知らない項目"),
        ({"default": "甲", "categories": [{"name": "甲" * 31, "color": 1}]}, "長すぎます"),
        ({"version": 2, "default": "甲", "categories": [{"name": "甲", "color": 1}]}, "version"),
        ({"default": "甲", "categories": [{"name": "甲", "color": 1, "keywords": ["語" + str(i) for i in range(501)]}]}, "多すぎます"),
    ],
)
def test_invalid_configs_are_rejected_without_echoing_content(data, message):
    with pytest.raises(CategoryConfigError) as excinfo:
        parse_config(data)
    assert message in str(excinfo.value)
    assert SECRET not in str(excinfo.value)


def test_notes_starting_with_underscore_are_ignored():
    config = parse_config({"_note": "メモ", "default": "甲", "categories": [{"name": "甲", "color": 1, "_memo": 1}]})
    assert config.names == ("甲",)


def test_sample_file_is_valid_json_with_utf8():
    data = json.loads(categories.SAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    assert parse_config(data).names == ("仕事", "学び", "地域", "暮らし")


# ------------------------------------------------------------
# 設定の読み先の順と、読めないときに見本へ戻すこと
# ------------------------------------------------------------

def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


ONE = {"default": "環境の甲", "categories": [{"name": "環境の甲", "color": 5}]}
TWO = {"default": "ファイルの甲", "categories": [{"name": "ファイルの甲", "color": 5}]}
THREE = {"default": "手元の甲", "categories": [{"name": "手元の甲", "color": 5}]}


def test_load_order(tmp_path):
    env_json = json.dumps(ONE, ensure_ascii=False)
    env_file = str(_write(tmp_path / "file.json", TWO))
    local = _write(tmp_path / "local.json", THREE)

    config, status = categories.load_config({categories.ENV_JSON: env_json, categories.ENV_FILE: env_file}, local)
    assert (config.names, status.source) == (("環境の甲",), "env")
    config, status = categories.load_config({categories.ENV_FILE: env_file}, local)
    assert (config.names, status.source) == (("ファイルの甲",), "file")
    config, status = categories.load_config({}, local)
    assert (config.names, status.source) == (("手元の甲",), "local")
    config, status = categories.load_config({}, tmp_path / "missing.json")
    assert status.source == "sample" and status.error is None
    config, status = categories.load_config({categories.ENV_JSON: "   "}, None)
    assert status.source == "sample"


def test_broken_config_falls_back_to_sample_and_logs_without_content(tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="task_sync")
    broken = '{"default": "' + SECRET + '", "categories": [ '
    config, status = categories.load_config({categories.ENV_JSON: broken}, None)
    assert status.source == "sample" and config.names == categories.sample_config().names
    assert status.error and "CATEGORY_CONFIG_JSON" in status.error and "JSON として読めません" in status.error
    assert SECRET not in status.error
    assert SECRET not in caplog.text and "見本の設定を使います" in caplog.text

    config, status = categories.load_config({categories.ENV_FILE: str(tmp_path / "missing.json")}, None)
    assert status.source == "sample" and "開けません" in status.error

    bad_file = tmp_path / "bad.json"
    bad_file.write_bytes("{}".encode("utf-16"))
    config, status = categories.load_config({categories.ENV_FILE: str(bad_file)}, None)
    assert status.source == "sample" and status.error


def test_local_file_path_is_private_and_gitignored():
    assert categories.LOCAL_CONFIG_PATH == ROOT / "private" / "categories.json"
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "private/" in gitignore


def test_reload_and_set_active(reallike):
    categories.set_active_config(reallike)
    assert categories.active_config().names == tuple(ORDER)
    assert categories.config_status().source == categories.SOURCE_FILE
    categories.reload_config(environ={}, local_path=None)
    assert categories.active_config().source == categories.SOURCE_SAMPLE


# ------------------------------------------------------------
# scripts/category_config.py（手元で確かめる・試す・1行にする）
# ------------------------------------------------------------

def _run_tool(*args: str, env_extra: dict | None = None):
    env = {k: v for k, v in os.environ.items() if k not in (categories.ENV_JSON, categories.ENV_FILE)}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "category_config.py"), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


def test_tool_check_prints_counts_only():
    result = _run_tool("check", str(REALLIKE_PATH))
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("使えます: カテゴリ 4 個")
    assert all(name not in result.stdout for name in ORDER)


def test_tool_try_shows_category_and_reason():
    result = _run_tool("try", str(REALLIKE_PATH), "会議の議事録", "見本会の会議")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"会議の議事録 → {PERSONAL}（色 4・理由: 当てはまる語なし（決まりのカテゴリ））",
        f"見本会の会議 → {GROUP1}（色 2・理由: 見本会・会議）",
    ]


def test_tool_env_makes_one_line_that_reads_back_the_same(reallike):
    result = _run_tool("env", str(REALLIKE_PATH))
    assert result.returncode == 0, result.stderr
    line = result.stdout.strip()
    assert "\n" not in line
    config, status = categories.load_config({categories.ENV_JSON: line}, local_path=None)
    assert status.error is None
    assert config.categories == reallike.categories and config.exclude == reallike.exclude


def test_tool_rejects_broken_file(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text('{"default": "架空", ', encoding="utf-8")
    result = _run_tool("check", str(broken))
    assert result.returncode == 1
    assert "JSON として読めません" in result.stderr


def test_tool_without_file_uses_the_app_order(tmp_path):
    result = _run_tool("check", env_extra={categories.ENV_FILE: str(REALLIKE_PATH)})
    assert result.returncode == 0 and "読み先: file" in result.stdout
