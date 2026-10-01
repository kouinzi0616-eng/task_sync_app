"""B28: 画面のファイルの静的検査（ブラウザを使わず、ファイルの中身だけで確かめる）。

- 入力や API の応答を HTML として解釈させる書き方（innerHTML への代入など）が無いこと
- HTML にインラインの script・style・イベント属性が無いこと（CSP で禁止しているため）
- 分けたファイル（app.js・app.css）が正しい種類で配信されること
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

JS_FILES = sorted(FRONTEND.glob("*.js"))
HTML_FILES = sorted(FRONTEND.glob("*.html"))

# 文字を HTML・コードとして解釈させる書き方。画面の JS では一切使わない
FORBIDDEN_JS = {
    "innerHTML": re.compile(r"\.innerHTML\b"),
    "outerHTML": re.compile(r"\.outerHTML\b"),
    "insertAdjacentHTML": re.compile(r"\binsertAdjacentHTML\b"),
    "document.write": re.compile(r"\bdocument\s*\.\s*write(ln)?\b"),
    "eval": re.compile(r"(?<![\w.])eval\s*\("),
    "new Function": re.compile(r"\bnew\s+Function\s*\("),
    "文字列の setTimeout・setInterval": re.compile(r"\bset(Timeout|Interval)\s*\(\s*['\"`]"),
    "on〜 属性の設定": re.compile(r"\.setAttribute\s*\(\s*['\"]on", re.IGNORECASE),
    "style 属性の設定": re.compile(r"\.setAttribute\s*\(\s*['\"]style['\"]", re.IGNORECASE),
    "javascript: の URL": re.compile(r"javascript:", re.IGNORECASE),
}

TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)(\s[^<>]*)?>")
ATTR_NAME_RE = re.compile(r"\s([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?=\s*=|\s|/?$)")


def test_frontend_has_js_and_html_files():
    names = {p.name for p in JS_FILES} | {p.name for p in HTML_FILES}
    assert {"app.js", "sw.js", "index.html"} <= names


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_js_does_not_use_html_injection_sinks(path):
    source = path.read_text(encoding="utf-8")
    found = []
    for label, pattern in FORBIDDEN_JS.items():
        for match in pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            found.append(f"{path.name}:{line_no}: {label}")
    assert not found, "HTML として解釈させる書き方が残っています:\n" + "\n".join(found)


def test_static_check_catches_inner_html_assignment():
    # 検査そのものが働くことの確認（架空のコード片）
    sample = "list.innerHTML = '<li>' + task.title + '</li>';"
    assert FORBIDDEN_JS["innerHTML"].search(sample)
    assert not FORBIDDEN_JS["innerHTML"].search("node.textContent = task.title;")


def _tags(html: str):
    for match in TAG_RE.finditer(html):
        name = match.group(1).lower()
        attrs_text = match.group(2) or ""
        # 属性の値（"..."）を取り除いてから属性名だけを拾う
        bare = re.sub(r'"[^"]*"|\'[^\']*\'', '""', attrs_text)
        attrs = {a.lower() for a in ATTR_NAME_RE.findall(bare)}
        yield name, attrs, match


@pytest.mark.parametrize("path", HTML_FILES, ids=lambda p: p.name)
def test_html_has_no_inline_script_style_or_handlers(path):
    html = path.read_text(encoding="utf-8")
    problems = []
    for name, attrs, match in _tags(html):
        line_no = html.count("\n", 0, match.start()) + 1
        if name == "style":
            problems.append(f"{line_no}: <style> 要素")
        if "style" in attrs:
            problems.append(f"{line_no}: style 属性")
        handlers = sorted(a for a in attrs if a.startswith("on"))
        if handlers:
            problems.append(f"{line_no}: イベント属性 {handlers}")
        if name == "script" and "src" not in attrs:
            problems.append(f"{line_no}: src の無い <script>")
    for body in re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I):
        if body.strip():
            problems.append("<script> の中にコードがある")
    if re.search(r"javascript:", html, re.I):
        problems.append("javascript: の URL")
    assert not problems, f"{path.name}:\n" + "\n".join(problems)


def test_index_loads_split_files(client):
    html = client.get("/").text
    assert '<link rel="stylesheet" href="/app.css">' in html
    assert '<script src="/app.js" defer></script>' in html


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/app.js", "application/javascript"),
        ("/app.css", "text/css"),
        ("/index.html", "text/html"),
    ],
)
def test_split_files_are_served_without_stale_cache(client, path, content_type):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    # 画面の本体は毎回サーバーに確かめさせる（古い画面が残らないように）
    assert response.headers["cache-control"] == "no-cache"
