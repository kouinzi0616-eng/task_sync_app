"""B28: manifest.json と maskable アイコン。

- アイコンは用途 any と maskable を分ける（"any maskable" の一緒書きにしない）
- maskable のアイコンは端まで背景を塗り、絵は中心の「安全な円」（半径 40%）に収める
- theme_color を画面の上端の色（app.css の --brand）にそろえ、向きの固定はしない
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MANIFEST = json.loads((FRONTEND / "manifest.json").read_text(encoding="utf-8"))


def _load_icon_tool():
    spec = importlib.util.spec_from_file_location("tsa_icons", ROOT / "scripts" / "make_maskable_icons.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


icons_tool = _load_icon_tool()


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _brand_color() -> str:
    css = (FRONTEND / "app.css").read_text(encoding="utf-8")
    return re.search(r"--brand:\s*(#[0-9a-fA-F]{6})", css).group(1).lower()


def test_theme_color_matches_the_screen():
    brand = _brand_color()
    assert MANIFEST["theme_color"].lower() == brand
    assert MANIFEST["background_color"].lower() == brand
    for name in ("index.html", "offline.html"):
        path = FRONTEND / name
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        meta = re.search(r'<meta name="theme-color" content="([^"]+)">', html)
        assert meta and meta.group(1).lower() == brand, name


def test_orientation_is_not_locked():
    assert "orientation" not in MANIFEST


def test_icons_are_split_into_any_and_maskable():
    purposes = {}
    for icon in MANIFEST["icons"]:
        assert icon["purpose"] in {"any", "maskable"}, icon  # 一緒書き（"any maskable"）にしない
        purposes.setdefault(icon["purpose"], set()).add(icon["sizes"])
    assert purposes == {"any": {"192x192", "512x512"}, "maskable": {"192x192", "512x512"}}


@pytest.mark.parametrize("icon", MANIFEST["icons"], ids=lambda i: i["src"])
def test_manifest_icons_are_served_with_the_declared_size(client, icon):
    response = client.get(icon["src"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    width, height = _png_size(response.content)
    assert f"{width}x{height}" == icon["sizes"]


def test_unknown_icon_names_are_404(client):
    for path in ("/icon-999.png", "/icon-maskable-999.png", "/icon-..png"):
        assert client.get(path).status_code == 404, path


MASKABLE = [icon for icon in MANIFEST["icons"] if icon["purpose"] == "maskable"]


@pytest.mark.parametrize("icon", MASKABLE, ids=lambda i: i["src"])
def test_maskable_icon_is_full_bleed_and_keeps_content_in_safe_zone(icon):
    width, height, pixels = icons_tool.read_png(FRONTEND / icon["src"].lstrip("/"))
    assert width == height
    # 透明な画素が無い（端まで塗ってある）
    assert all(px[3] == 255 for row in pixels for px in row)
    # 安全な円の外は背景色だけ（切り抜かれても絵が欠けない）
    center = (width - 1) / 2
    radius = icons_tool.SAFE_ZONE_RADIUS * width
    background = icons_tool.BACKGROUND
    outside = 0
    for y, row in enumerate(pixels):
        for x, px in enumerate(row):
            if math.hypot(x - center, y - center) > radius:
                outside += 1
                assert all(abs(px[k] - background[k]) <= 2 for k in range(3)), (x, y, px)
    assert outside > width * height * 0.4  # 円の外を十分に調べた
    # 円の中には絵がある（白いリストの部分）
    assert pixels[height // 2][width // 2][:3] == (255, 255, 255)


@pytest.mark.parametrize("size", sorted(icons_tool.OUTPUTS))
def test_maskable_icons_match_the_generator(size):
    """作り方（scripts/make_maskable_icons.py）と、置いてある画像が一致する"""
    _, _, source = icons_tool.read_png(icons_tool.SOURCE)
    expected = icons_tool.make_maskable(source, size)
    _, _, actual = icons_tool.read_png(icons_tool.OUTPUTS[size])
    assert actual == expected


def test_png_round_trip(tmp_path):
    pixels = [[(10, 20, 30, 255), (40, 50, 60, 128)], [(0, 0, 0, 0), (255, 255, 255, 255)]]
    path = tmp_path / "tiny.png"
    icons_tool.write_png(path, pixels)
    assert icons_tool.read_png(path) == (2, 2, pixels)
