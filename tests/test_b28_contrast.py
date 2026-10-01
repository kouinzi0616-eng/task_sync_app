"""B28: 文字色と背景の対比（コントラスト比）を app.css から計算して確かめる。

計算は scripts/contrast.py（標準ライブラリだけ）。表を見たいときは
`python scripts/contrast.py` を実行する。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_contrast():
    spec = importlib.util.spec_from_file_location("tsa_contrast", ROOT / "scripts" / "contrast.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass が自分のモジュールを探せるように
    spec.loader.exec_module(module)
    return module


contrast = _load_contrast()
CSS = contrast.CSS_PATH.read_text(encoding="utf-8")
RULES, NESTED = contrast.parse_css(CSS)
PROPS = contrast.custom_properties(RULES)


# ------------------------------------------------------------
# 計算そのものが正しいこと（WCAG の値と照らし合わせる）
# ------------------------------------------------------------

def test_contrast_formula_matches_known_values():
    white = contrast.parse_color("#ffffff")
    black = contrast.parse_color("black")
    assert contrast.contrast_ratio(white, black) == pytest.approx(21.0)
    assert contrast.contrast_ratio(white, white) == pytest.approx(1.0)
    # #767676 は白の上でちょうど 4.5 を少し超える、よく知られた灰色
    assert contrast.contrast_ratio(contrast.parse_color("#767676"), white) == pytest.approx(4.54, abs=0.01)
    # もとの画面の色（白の上の #667eea）は 4.5 に届いていなかった
    assert contrast.contrast_ratio(contrast.parse_color("#667eea"), white) < 4.5


def test_translucent_background_is_blended_over_gradient():
    css = """
    :root { --a: #000000; }
    body { background: linear-gradient(135deg, #ffffff 0%, var(--a) 100%); }
    .box { background: rgba(255, 255, 255, 0.5); color: #000; }
    """
    rules, _ = contrast.parse_css(css)
    props = contrast.custom_properties(rules)
    samples = contrast.effective_background([".box", "body"], rules, props)
    assert len(samples) > 2
    assert samples[0][:3] == (255, 255, 255)
    assert samples[-1][:3] == (128, 128, 128)


def test_parse_color_forms():
    assert contrast.parse_color("#fff") == (255, 255, 255, 1.0)
    assert contrast.parse_color("rgba(0, 0, 0, 0.2)") == (0, 0, 0, 0.2)
    assert contrast.parse_color("rgb(1 2 3)") == (1, 2, 3, 1.0)


# ------------------------------------------------------------
# 画面の全色が基準以上であること
# ------------------------------------------------------------

CHECKS = contrast.run_checks(CSS)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: f"{c.kind}:{c.target}:{c.background}")
def test_every_color_pair_meets_the_minimum(check):
    assert check.ratio >= check.minimum, (
        f"{check.note}（{check.target}）: {check.foreground_hex} / {check.background_hex} "
        f"= {check.ratio:.2f}（基準 {check.minimum}）"
    )


def test_all_text_colors_reach_4_5():
    text_checks = [c for c in CHECKS if c.kind == "文字"]
    assert len(text_checks) == len(contrast.TEXT_PAIRS)
    assert min(c.ratio for c in text_checks) >= 4.5


def test_command_exits_zero(capsys):
    assert contrast.main([]) == 0
    out = capsys.readouterr().out
    assert "| 文字 |" in out and "**不足**" not in out


# ------------------------------------------------------------
# 表の漏れが無いこと（色を足したのに確かめていない、を防ぐ）
# ------------------------------------------------------------

def _has_color(value: str) -> bool:
    return bool(contrast.color_tokens(contrast.resolve(value, PROPS)))


def test_every_text_color_rule_is_checked():
    declared = {sel for sel, decls in RULES.items() if "color" in decls}
    checked = {fg for fg, _, _ in contrast.TEXT_PAIRS}
    assert declared - checked == set(), "color を書いた規則が TEXT_PAIRS にありません"
    assert checked - set(RULES) == set(), "TEXT_PAIRS に、app.css に無い規則があります"


def test_every_background_rule_is_checked():
    declared = {
        sel for sel, decls in RULES.items()
        if any(_has_color(decls[p]) for p in ("background", "background-color") if p in decls)
    }
    used = {sel for _, chain, _ in contrast.TEXT_PAIRS for sel in chain}
    used |= {sel for _, _, chain, _ in contrast.NON_TEXT_PAIRS for sel in chain}
    assert declared - used == set(), "背景色を書いた規則が、どの組にも使われていません"
    assert used - set(RULES) == set()


def test_every_focus_outline_is_checked():
    declared = {
        sel for sel, decls in RULES.items()
        if "outline" in decls and _has_color(decls["outline"])
    }
    checked = {sel for sel, prop, _, _ in contrast.NON_TEXT_PAIRS if prop == "outline"}
    assert declared - checked == set()


def test_media_queries_do_not_change_colors():
    # @media の中で色を変えると上の計算から漏れるので、色は書かない
    for selector, decls in NESTED.items():
        for prop in ("color", "background", "background-color", "outline", "border-color"):
            assert prop not in decls or not _has_color(decls[prop]), selector


def test_no_opacity_tricks_on_text():
    # 透明度で文字を薄くすると計算から漏れるので使わない
    for selector, decls in {**RULES, **NESTED}.items():
        assert "opacity" not in decls, selector
