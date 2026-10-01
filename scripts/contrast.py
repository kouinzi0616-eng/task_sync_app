"""画面の文字色と背景の対比（コントラスト比）を frontend/app.css から計算する。

WCAG 2.2 の式（相対輝度）で計算し、文字は 4.5:1 以上、フォーカス枠・入力欄の枠は 3:1 以上を求める。
半透明の背景は下の背景と重ねて、グラデーションは途中の色も含めて、いちばん低い値を使う。

使い方（標準ライブラリだけで動く）:
    python scripts/contrast.py      # 表（Markdown）を出す。基準に届かない色があれば終了コード 1

tests/test_b28_contrast.py が同じ計算を回し、app.css で color や background を書いた規則が
下の表（TEXT_PAIRS・NON_TEXT_PAIRS）に漏れなく載っていることも確かめる。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "frontend" / "app.css"

TEXT_MIN = 4.5  # 文字（WCAG 2.2 1.4.3。大きい文字も同じ基準で見る）
NON_TEXT_MIN = 3.0  # フォーカス枠・入力欄の枠（WCAG 2.2 1.4.11）

# (文字の色を決める規則, 背景を決める規則（内側 → 外側の順）, 何の文字か)
TEXT_PAIRS: list[tuple[str, list[str], str]] = [
    ("body", [".card"], "カードの中の見出し・本文（body の色を継ぐ）"),
    (".header", ["body"], "いちばん上の見出し（グラデーションの上）"),
    (".update-banner", [".update-banner"], "「新しい版があります」の案内"),
    (".update-banner button", [".update-banner button"], "案内の「更新する」ボタン"),
    (".install-prompt", [".install-prompt", "body"], "ホーム画面に追加の案内"),
    (".install-prompt button", [".install-prompt button"], "「追加」ボタン"),
    (".tab", [".tab", "body"], "選んでいないタブ"),
    ('.tab[aria-selected="true"]', ['.tab[aria-selected="true"]'], "選んでいるタブ"),
    (".input-group label", [".card"], "入力欄の見出し"),
    ("textarea", ["textarea"], "入力した文字"),
    ("textarea::placeholder", ["textarea"], "入力欄の例文（placeholder）"),
    (".btn-primary", [".btn-primary"], "「解析する」ボタン"),
    ('.btn-primary[aria-disabled="true"]', ['.btn-primary[aria-disabled="true"]'], "解析中の「解析する」ボタン"),
    (".btn-success", [".btn-success"], "「カレンダー用ファイルを保存」ボタン"),
    (".btn-success", [".btn-success:hover"], "「カレンダー用ファイルを保存」ボタン（指・カーソルを乗せたとき）"),
    (".task-title", [".task-item"], "結果の題名"),
    (".badge-cat-0", [".badge-cat-0"], "カテゴリの印（色の番号が無いとき）"),
    (".badge-cat-1", [".badge-cat-1"], "カテゴリの印（色 1）"),
    (".badge-cat-2", [".badge-cat-2"], "カテゴリの印（色 2）"),
    (".badge-cat-3", [".badge-cat-3"], "カテゴリの印（色 3）"),
    (".badge-cat-4", [".badge-cat-4"], "カテゴリの印（色 4）"),
    (".badge-cat-5", [".badge-cat-5"], "カテゴリの印（色 5）"),
    (".badge-cat-6", [".badge-cat-6"], "カテゴリの印（色 6）"),
    (".deadline", [".task-item"], "期限"),
    (".task-note", [".task-item"], "注意（存在しない日付など）"),
    (".task-failed .task-note", [".task-item"], "解析できなかった行の理由"),
    (".task-reading", [".task-item"], "読み取り（どう読んだか）"),
    (".task-reason", [".task-item"], "カテゴリの理由（当たった語）"),
    (".badge-review", [".badge-review"], "「要確認」の印"),
    (".badge-overdue", [".badge-overdue"], "「期限切れ」の印"),
    (".loading", [".card"], "「解析中…」"),
    (".error", [".error"], "エラーの知らせ"),
    (".success", [".success"], "結果の知らせ"),
    (".example", [".card"], "日付の書き方の例"),
    (".stat-number", [".stat-card"], "統計の数"),
    (".stat-label", [".stat-card"], "統計の見出し"),
    (".muted", [".card"], "控えめな案内文"),
    (".offline-link", [".card"], "オフライン画面の「もう一度読み込む」"),
    # B29: 端末に保存したタスク（本人の番・一覧・書き出しと読み込み）
    (".btn-secondary", [".btn-secondary"], "「端末に保存」「JSON に書き出す」などのボタン"),
    (".hint", [".card"], "ボタンの下の補足"),
    (".list-summary", [".card"], "本人の番・一覧の件数"),
    (".warning", [".warning"], "一時の保存に切り替えたときの注意"),
    (".badge-lane", [".badge-lane"], "レーンの印"),
    (".badge-status", [".badge-status"], "状態の印（一覧）"),
    (".badge-stale", [".badge-stale"], "「2日以上動きなし」の印"),
    (".task-next", [".task-item"], "Notion の台帳の「本人の番」の欄"),
    (".field label", [".task-item"], "入力欄の見出し（タスクの中）"),
    (".field label", [".card"], "入力欄の見出し（カードの上）"),
    (".field input", [".field input"], "次に本人がすること（入力した文字）"),
    (".field select", [".field select"], "レーンの選択（選んだ文字）"),
    (".btn-small", [".btn-small"], "状態を変えるボタン"),
    (".btn-danger", [".btn-small"], "「削除」ボタン"),
    (".settings summary", [".card"], "「レーン名の設定」の開閉"),
]

# (枠の色を決める規則, 属性, 背景を決める規則（内側 → 外側）, 何の枠か)
NON_TEXT_PAIRS: list[tuple[str, str, list[str], str]] = [
    (".tab:focus-visible", "outline", ["body"], "タブのフォーカス枠"),
    (".install-prompt button:focus-visible", "outline", [".install-prompt", "body"], "「追加」のフォーカス枠"),
    (".tab-content:focus-visible", "outline", ["body"], "タブの中身のフォーカス枠"),
    (".btn:focus-visible", "outline", [".card"], "ボタンのフォーカス枠"),
    (".update-banner button:focus-visible", "outline", [".update-banner"], "「更新する」のフォーカス枠"),
    ("textarea:focus-visible", "outline", [".card"], "入力欄のフォーカス枠"),
    (".offline-link:focus-visible", "outline", [".card"], "リンクのフォーカス枠"),
    (".btn-small:focus-visible", "outline", [".task-item"], "状態を変えるボタンのフォーカス枠"),
    (".field input:focus-visible", "outline", [".task-item"], "入力欄（次に本人がすること）のフォーカス枠"),
    (".field select:focus-visible", "outline", [".task-item"], "レーンの選択のフォーカス枠"),
    (".settings summary:focus-visible", "outline", [".card"], "「レーン名の設定」のフォーカス枠"),
    (".card-title:focus-visible", "outline", [".card"], "見出し（状態を変えたあとの移り先）のフォーカス枠"),
    (".field input", "border", [".task-item"], "入力欄の枠（タスクの中）"),
    (".field select", "border", [".task-item"], "選択の枠（タスクの中）"),
    (".btn-small", "border", [".task-item"], "状態を変えるボタンの枠"),
    (".btn-secondary", "border", [".card"], "白いボタンの枠"),
    ("textarea", "border", [".card"], "入力欄の枠"),
    ("textarea:focus", "border-color", [".card"], "入力中の入力欄の枠"),
]

NAMED_COLORS = {
    "white": (255, 255, 255, 1.0),
    "black": (0, 0, 0, 1.0),
    "transparent": (0, 0, 0, 0.0),
}
COLOR_TOKEN_RE = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:" + "|".join(NAMED_COLORS) + r")\b"
)

Color = tuple[int, int, int, float]  # r, g, b（0〜255）, a（0〜1）


# ------------------------------------------------------------
# CSS を読む（このアプリの app.css が読めれば十分な、小さな読み取り）
# ------------------------------------------------------------

def _top_level_blocks(text: str) -> list[tuple[str, str]]:
    """{ } の対応を数えて、いちばん外側の (前置き, 中身) を順に返す"""
    blocks = []
    depth = 0
    prelude_start = 0
    body_start = 0
    prelude = ""
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                prelude = text[prelude_start:i].strip()
                body_start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("} が多すぎます")
            if depth == 0:
                blocks.append((prelude, text[body_start:i]))
                prelude_start = i + 1
    if depth != 0:
        raise ValueError("{ が閉じていません")
    return blocks


def _declarations(body: str) -> dict[str, str]:
    decls = {}
    for part in body.split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            decls[name.strip().lower()] = " ".join(value.split())
    return decls


def parse_css(css: str) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """(ふつうの規則, @media などの中の規則) を {セレクタ: {属性: 値}} で返す"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: dict[str, dict[str, str]] = {}
    nested: dict[str, dict[str, str]] = {}
    for prelude, body in _top_level_blocks(css):
        if prelude.startswith("@"):
            for inner_prelude, inner_body in _top_level_blocks(body):
                for selector in inner_prelude.split(","):
                    key = f"{prelude} {' '.join(selector.split())}"
                    nested.setdefault(key, {}).update(_declarations(inner_body))
            continue
        for selector in prelude.split(","):
            key = " ".join(selector.split())
            rules.setdefault(key, {}).update(_declarations(body))
    return rules, nested


def custom_properties(rules: dict[str, dict[str, str]]) -> dict[str, str]:
    return {k: v for k, v in rules.get(":root", {}).items() if k.startswith("--")}


def resolve(value: str, props: dict[str, str]) -> str:
    """var(--x) を :root の値に置きかえる"""
    for _ in range(10):
        new = re.sub(r"var\(\s*(--[\w-]+)\s*\)", lambda m: props[m.group(1)], value)
        if new == value:
            return new
        value = new
    raise ValueError(f"var() が深すぎます: {value}")


def parse_color(token: str) -> Color:
    token = token.strip().lower()
    if token in NAMED_COLORS:
        return NAMED_COLORS[token]
    if token.startswith("#"):
        digits = token[1:]
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits)
        r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
        a = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return (r, g, b, a)
    match = re.fullmatch(r"rgba?\(([^)]*)\)", token)
    if match:
        parts = [p for p in re.split(r"[\s,/]+", match.group(1)) if p]
        r, g, b = (int(float(p)) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return (r, g, b, a)
    raise ValueError(f"色として読めません: {token}")


def color_tokens(value: str) -> list[str]:
    return [m.group(0) for m in COLOR_TOKEN_RE.finditer(value)]


# ------------------------------------------------------------
# 色の計算
# ------------------------------------------------------------

def _channel(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: Color) -> float:
    r, g, b, _ = color
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: Color, b: Color) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def blend(top: Color, bottom: Color) -> Color:
    """半透明の色を、下の（不透明な）色の上に重ねる"""
    a = top[3]
    return (
        round(top[0] * a + bottom[0] * (1 - a)),
        round(top[1] * a + bottom[1] * (1 - a)),
        round(top[2] * a + bottom[2] * (1 - a)),
        1.0,
    )


def _gradient_samples(stops: list[Color], steps: int = 20) -> list[Color]:
    """グラデーションの色を等間隔に取り出す（sRGB で直線に混ぜる。ブラウザの既定と同じ）"""
    samples = []
    segments = len(stops) - 1
    for i in range(steps + 1):
        t = i / steps * segments
        k = min(int(t), segments - 1)
        f = t - k
        a, b = stops[k], stops[k + 1]
        samples.append(tuple(round(a[j] + (b[j] - a[j]) * f) for j in range(3)) + (1.0,))
    return samples


def background_layer(selector: str, rules, props) -> list[Color] | None:
    """その規則の背景（無ければ None）。グラデーションは途中の色の一覧"""
    decls = rules[selector]
    value = decls.get("background-color") or decls.get("background")
    if not value:
        return None
    value = resolve(value, props)
    tokens = color_tokens(value)
    if not tokens:
        return None
    if "gradient(" in value:
        return _gradient_samples([parse_color(t) for t in tokens])
    return [parse_color(tokens[0])]


def effective_background(chain: list[str], rules, props) -> list[Color]:
    """内側 → 外側の規則の背景を重ねた、不透明な色の一覧"""
    result: list[Color] | None = None
    for selector in reversed(chain):
        layer = background_layer(selector, rules, props)
        if layer is None:
            continue
        if all(c[3] >= 1.0 for c in layer):
            result = layer
            continue
        if result is None:
            raise ValueError(f"{selector} の半透明の背景の下に、不透明な背景がありません")
        if len(layer) != 1:
            raise ValueError(f"{selector}: 半透明のグラデーションには対応していません")
        result = [blend(layer[0], below) for below in result]
    if result is None:
        raise ValueError(f"背景が決まりません: {chain}")
    return result


def _hex(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color[:3])


@dataclass
class Check:
    kind: str  # 文字 / 枠
    target: str
    background: str
    foreground_hex: str
    background_hex: str
    ratio: float
    minimum: float
    note: str

    @property
    def ok(self) -> bool:
        return self.ratio >= self.minimum


def _describe_background(samples: list[Color], worst: Color) -> str:
    if len(samples) == 1:
        return _hex(samples[0])
    return f"{_hex(samples[0])}→{_hex(samples[-1])}（最小は {_hex(worst)}）"


def _measure(fg: Color, backgrounds: list[Color]) -> tuple[float, Color]:
    pairs = []
    for bg in backgrounds:
        color = blend(fg, bg) if fg[3] < 1.0 else fg
        pairs.append((contrast_ratio(color, bg), bg))
    return min(pairs, key=lambda p: p[0])


def run_checks(css: str | None = None) -> list[Check]:
    if css is None:
        css = CSS_PATH.read_text(encoding="utf-8")
    rules, _ = parse_css(css)
    props = custom_properties(rules)
    checks = []
    for fg_selector, chain, note in TEXT_PAIRS:
        value = rules[fg_selector].get("color")
        if value is None:
            raise ValueError(f"{fg_selector} に color がありません")
        fg = parse_color(color_tokens(resolve(value, props))[0])
        backgrounds = effective_background(chain, rules, props)
        ratio, worst = _measure(fg, backgrounds)
        checks.append(Check("文字", fg_selector, " ← ".join(chain), _hex(fg),
                            _describe_background(backgrounds, worst), ratio, TEXT_MIN, note))
    for selector, prop, chain, note in NON_TEXT_PAIRS:
        value = rules[selector].get(prop)
        if value is None:
            raise ValueError(f"{selector} に {prop} がありません")
        fg = parse_color(color_tokens(resolve(value, props))[0])
        backgrounds = effective_background(chain, rules, props)
        ratio, worst = _measure(fg, backgrounds)
        checks.append(Check("枠", f"{selector}（{prop}）", " ← ".join(chain), _hex(fg),
                            _describe_background(backgrounds, worst), ratio, NON_TEXT_MIN, note))
    return checks


def markdown_table(checks: list[Check]) -> str:
    lines = [
        "| 種類 | 何か | 規則 | 色 | 背景 | 対比 | 基準 | 判定 |",
        "|------|------|------|----|------|-----:|-----:|------|",
    ]
    for c in checks:
        lines.append(
            f"| {c.kind} | {c.note} | `{c.target}` | {c.foreground_hex} | {c.background_hex} "
            f"| {c.ratio:.2f} | {c.minimum:.1f} | {'OK' if c.ok else '**不足**'} |"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    checks = run_checks()
    if "--json" in argv:
        print(json.dumps([c.__dict__ | {"ok": c.ok} for c in checks], ensure_ascii=False, indent=2))
    else:
        print(markdown_table(checks))
    bad = [c for c in checks if not c.ok]
    if bad:
        print(f"\n基準に届かない色が {len(bad)} 件あります", file=sys.stderr)
        return 1
    print(f"\n全 {len(checks)} 件が基準以上（文字 {TEXT_MIN}・枠 {NON_TEXT_MIN}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
