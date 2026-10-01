"""B27: 一本化する前（316d9c7）のカテゴリ判定を、語の表を引数にして再現する（検算用の部品。テストではない）。

- legacy_classify: 前の画面・API（backend/category_classifier.py）の決め方。
  当たった語の数がいちばん多いカテゴリ。同点は order の順。どれにも当たらなければ default。
- legacy_to_config: 前の2つの語の表（画面・API 用と、カレンダー同期用の normalizer.py）を、
  新しい設定（categories.py が読む JSON の形）にする。

実物の語の表はリポジトリに置かない。テスト（test_b27_categories.py）は架空の語の表で、
この変換と、変換した設定で前と同じ判定になることを確かめる。
実物の設定は、同じ legacy_to_config で手元で一度だけ作り、件数だけを記録した。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

KANA_ONLY = re.compile(r"[ぁ-ゟ゠-ヿー]+")


def legacy_classify(text: str, keywords: Mapping[str, Iterable[str]], order: list[str], default: str) -> str:
    """前の画面・API の決め方（部分一致・小文字にして比べる）"""
    lowered = text.lower()
    scores = {name: sum(1 for word in keywords.get(name, ()) if word.lower() in lowered) for name in order}
    best = max(scores.values())
    if best == 0:
        return default
    return next(name for name in order if scores[name] == best)


def legacy_to_config(
    api_keywords: Mapping[str, list[str]],
    calendar_keywords: Mapping[str, list[str]],
    order: list[str],
    colors: Mapping[str, int],
    default: str,
    group_names: Iterable[str] = (),
    category_exclude: Mapping[str, list[str]] | None = None,
    exclude: Iterable[str] = (),
) -> dict:
    """前の語の表 → 新しい設定（dict）。

    - カテゴリの順は order（前の画面・API の同点の順）。色は colors（1〜6）。
    - 語は「画面・API の語」の後ろに「カレンダー同期用にだけあった語」を足す（どちらの語も失わない）。
    - group_names（団体のカテゴリ）では、名前のかな書きと、名前の頭の部分（略称）を aliases にする。
    """
    category_exclude = category_exclude or {}
    groups = set(group_names)
    categories = []
    for name in order:
        api_words = list(api_keywords.get(name, []))
        words = api_words + [w for w in calendar_keywords.get(name, []) if w not in api_words]
        aliases = []
        if name in groups:
            aliases = [w for w in words if w != name and (KANA_ONLY.fullmatch(w) or name.startswith(w))]
        entry: dict = {
            "name": name,
            "color": colors[name],
            "keywords": [w for w in words if w != name and w not in aliases],
        }
        if aliases:
            entry["aliases"] = aliases
        if category_exclude.get(name):
            entry["exclude"] = list(category_exclude[name])
        categories.append(entry)
    return {"version": 1, "default": default, "exclude": list(exclude), "categories": categories}
