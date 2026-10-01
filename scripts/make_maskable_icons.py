"""PWA の maskable アイコン（端まで背景を塗ったアイコン）を、今のアイコンから作る。

Android などは、アイコンを丸や角丸の形に切り抜いて表示する。切り抜かれても絵が欠けないよう、
- 背景色で四角全体を塗り（透明な角を残さない）
- 今のアイコン（frontend/icon-512.png）を 80% に縮めて真ん中に置く
（大事な部分が、中心から半径 40% の「安全な円」に収まる）。
参考: https://web.dev/articles/maskable-icon

標準ライブラリ（zlib・struct）だけで PNG を読み書きする。Pillow などは使わない。

使い方:
    python scripts/make_maskable_icons.py   # frontend/icon-maskable-192.png・icon-maskable-512.png を作り直す
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SOURCE = FRONTEND / "icon-512.png"
OUTPUTS = {192: FRONTEND / "icon-maskable-192.png", 512: FRONTEND / "icon-maskable-512.png"}

BACKGROUND = (0x66, 0x7E, 0xEA)  # 今のアイコンの背景色（icon.svg の #667eea）
CONTENT_SCALE = 0.8  # 絵を置く大きさ（四角の一辺に対する割合）
SAFE_ZONE_RADIUS = 0.4  # 安全な円の半径（四角の一辺に対する割合）

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

Pixels = list[list[tuple[int, int, int, int]]]  # [y][x] = (r, g, b, a)


# ------------------------------------------------------------
# PNG の読み書き（8bit の RGB / RGBA・インターレース無しだけ）
# ------------------------------------------------------------

def _chunks(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("PNG ではありません")
    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        yield kind, body
        pos += 12 + length


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path: Path) -> tuple[int, int, Pixels]:
    data = path.read_bytes()
    width = height = 0
    channels = 0
    idat = bytearray()
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or color_type not in (2, 6) or interlace != 0:
                raise ValueError("8bit の RGB / RGBA（インターレース無し）だけ読めます")
            channels = 4 if color_type == 6 else 3
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    rows: Pixels = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = prev[i]
            up_left = prev[i - channels] if i >= channels else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError(f"知らないフィルタ {filter_type}")
        prev = line
        if channels == 4:
            rows.append([tuple(line[x * 4:x * 4 + 4]) for x in range(width)])
        else:
            rows.append([tuple(line[x * 3:x * 3 + 3]) + (255,) for x in range(width)])
    return width, height, rows


def write_png(path: Path, pixels: Pixels) -> None:
    """RGBA の PNG を書く（各行にフィルタ「Sub」を使う。毎回同じバイト列になる）"""
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        flat = bytes(v for px in row for v in px)
        raw.append(1)  # Sub
        raw += bytes((flat[i] - (flat[i - 4] if i >= 4 else 0)) & 0xFF for i in range(len(flat)))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    path.write_bytes(data)


# ------------------------------------------------------------
# 縮小（面積で平均する。透明度を考えて混ぜる）と合成
# ------------------------------------------------------------

def _weights(src_size: int, dst_size: int) -> list[list[tuple[int, float]]]:
    """縮小後の各画素が、元のどの画素をどれだけ含むか"""
    scale = src_size / dst_size
    table = []
    for d in range(dst_size):
        start, end = d * scale, (d + 1) * scale
        items = []
        s = int(start)
        while s < end and s < src_size:
            overlap = min(end, s + 1) - max(start, s)
            if overlap > 0:
                items.append((s, overlap / scale))
            s += 1
        table.append(items)
    return table


def resize_premultiplied(pixels: Pixels, size: int) -> list[list[tuple[float, float, float, float]]]:
    """正方形の絵を size×size に縮める。戻り値は (r*a, g*a, b*a, a) の形（a は 0〜1）"""
    src = len(pixels)
    table = _weights(src, size)
    pre = [[(r * a / 255, g * a / 255, b * a / 255, a / 255) for r, g, b, a in row] for row in pixels]
    # 先に横、次に縦
    horizontal = []
    for row in pre:
        out_row = []
        for items in table:
            acc = [0.0, 0.0, 0.0, 0.0]
            for x, w in items:
                px = row[x]
                for k in range(4):
                    acc[k] += px[k] * w
            out_row.append(tuple(acc))
        horizontal.append(out_row)
    result = []
    for items in table:
        out_row = []
        for x in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for y, w in items:
                px = horizontal[y][x]
                for k in range(4):
                    acc[k] += px[k] * w
            out_row.append(tuple(acc))
        result.append(out_row)
    return result


def make_maskable(source: Pixels, size: int) -> Pixels:
    inner = round(size * CONTENT_SCALE)
    offset = (size - inner) // 2
    content = resize_premultiplied(source, inner)
    out: Pixels = [[BACKGROUND + (255,) for _ in range(size)] for _ in range(size)]
    for y in range(inner):
        for x in range(inner):
            r, g, b, a = content[y][x]
            bg = BACKGROUND
            out[y + offset][x + offset] = (
                min(255, round(r + bg[0] * (1 - a))),
                min(255, round(g + bg[1] * (1 - a))),
                min(255, round(b + bg[2] * (1 - a))),
                255,
            )
    return out


def main() -> int:
    width, height, pixels = read_png(SOURCE)
    if width != height:
        print("元のアイコンが正方形ではありません", file=sys.stderr)
        return 1
    for size, path in OUTPUTS.items():
        write_png(path, make_maskable(pixels, size))
        print(f"作成: {path.relative_to(ROOT)}（{size}×{size}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
