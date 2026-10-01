"""B28: 画面のアクセシビリティ（HTML と JS の静的検査）。

- タブに WAI-ARIA の役割（tablist・tab・tabpanel）と aria-selected・aria-controls が付いていること
- 解析中・結果・エラーの知らせが aria-live の領域にあり、自動で消さないこと
動きそのもの（矢印キーで移る・読み上げ領域に文字が入る）は test_b28_frontend_js.py で確かめる。
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")


class _Collector(HTMLParser):
    """要素ごとに (タグ, 属性, 中の文字) を集める"""

    VOID = {"meta", "link", "br", "img", "input", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.elements: list[dict] = []
        self._stack: list[dict] = []
        self.html_attrs: dict = {}

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": dict(attrs), "text": ""}
        if tag == "html":
            self.html_attrs = element["attrs"]
        self.elements.append(element)
        if tag not in self.VOID:
            self._stack.append(element)

    def handle_endtag(self, tag):
        while self._stack:
            if self._stack.pop()["tag"] == tag:
                break

    def handle_data(self, data):
        for element in self._stack:
            element["text"] += data


def _parse(html: str) -> _Collector:
    collector = _Collector()
    collector.feed(html)
    return collector


DOC = _parse(INDEX)
BY_ID = {e["attrs"]["id"]: e for e in DOC.elements if "id" in e["attrs"]}


def _with_role(role: str) -> list[dict]:
    return [e for e in DOC.elements if e["attrs"].get("role") == role]


def test_page_language_and_landmarks():
    assert DOC.html_attrs.get("lang") == "ja"
    tags = [e["tag"] for e in DOC.elements]
    assert tags.count("main") == 1
    assert tags.count("h1") == 1
    assert "h3" not in tags  # 見出しは h1 → h2 の順にする


def test_tabs_follow_the_aria_tab_pattern():
    tablists = _with_role("tablist")
    assert len(tablists) == 1
    assert tablists[0]["attrs"].get("aria-label")

    tabs = _with_role("tab")
    panels = _with_role("tabpanel")
    assert len(tabs) == len(panels) == 3

    selected = [t for t in tabs if t["attrs"].get("aria-selected") == "true"]
    assert len(selected) == 1
    for tab in tabs:
        attrs = tab["attrs"]
        assert tab["tag"] == "button" and attrs.get("type") == "button"
        assert attrs.get("aria-selected") in {"true", "false"}
        # 選んでいるタブだけ Tab キーで止まる（ほかは矢印キーで移る）
        assert attrs.get("tabindex") == ("0" if attrs["aria-selected"] == "true" else "-1")
        panel = BY_ID[attrs["aria-controls"]]
        assert panel["attrs"].get("role") == "tabpanel"
        assert panel["attrs"].get("aria-labelledby") == attrs["id"]
        # 選んでいないタブの中身は hidden
        assert ("hidden" in panel["attrs"]) == (attrs["aria-selected"] == "false")


def test_status_messages_are_live_regions_and_start_empty():
    error = BY_ID["error"]["attrs"]
    assert error.get("role") == "alert"
    assert error.get("aria-live") == "assertive"
    for name in ("loading", "success"):
        attrs = BY_ID[name]["attrs"]
        assert attrs.get("role") == "status", name
        assert attrs.get("aria-live") == "polite", name
    # 中身は app.js が入れる。空のまま置いておき、空のときは場所を取らない（app.css の :not(:empty)）
    for name in ("loading", "error", "success"):
        assert BY_ID[name]["text"] == "", name


def test_messages_are_not_removed_by_timer():
    # もとは 3〜5 秒で知らせを消していた。読み上げの途中で消えないよう、タイマーは使わない
    assert "setTimeout" not in APP_JS
    assert "setInterval" not in APP_JS


def test_tab_keys_are_handled_in_js():
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert f"'{key}'" in APP_JS, key
    assert "aria-selected" in APP_JS


def test_form_controls_have_names():
    textarea = BY_ID["taskInput"]
    labels = [e for e in DOC.elements if e["tag"] == "label" and e["attrs"].get("for") == "taskInput"]
    assert textarea["tag"] == "textarea" and labels
    for element in DOC.elements:
        if element["tag"] == "button":
            assert element["text"].strip() or element["attrs"].get("aria-label"), element
            assert element["attrs"].get("type") == "button", element


def test_decorative_emoji_are_hidden_from_screen_readers():
    for element in DOC.elements:
        if element["tag"] in {"h1", "h2"}:
            # 見出しの絵文字は aria-hidden の span に入れている
            assert any(
                e["tag"] == "span" and e["attrs"].get("aria-hidden") == "true" and e["text"] in element["text"]
                for e in DOC.elements
            ), element


def test_viewport_allows_zoom():
    viewport = [e for e in DOC.elements if e["tag"] == "meta" and e["attrs"].get("name") == "viewport"]
    content = viewport[0]["attrs"]["content"].replace(" ", "")
    assert "user-scalable=no" not in content
    assert "maximum-scale" not in content
