"""Draw the Chrome extension icons (feature 011, tasks T002) with the standard library only.

Usage: uv run python scripts/make_extension_icons.py

A green price tag on a dark rounded square, written to extension/icons/icon-<n>.png for n = 16, 32, 48, 128.
Anti-aliasing is 4 x 4 supersampling. Run once; the PNG files are committed.
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "extension" / "icons"
BG = (0x1B, 0x28, 0x38)
TAG = (0xA4, 0xD0, 0x07)
SS = 4


def _rotate(x, y, angle):
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


def _in_polygon(x, y, poly):
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _in_rounded_square(x, y, r):
    """Unit square [0, 1]^2 with corner radius r."""
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r and 0 <= x <= 1 and 0 <= y <= 1


# a price tag pointing left, centred at the origin, then rotated -45 degrees (point towards the top left)
TAG_POLY = [(-0.36, 0.0), (-0.18, -0.2), (0.34, -0.2), (0.34, 0.2), (-0.18, 0.2)]
HOLE = (-0.14, 0.0, 0.055)
ANGLE = math.radians(-45)


def pixel(u, v):
    """Colour and alpha at unit coordinates (u, v)."""
    if not _in_rounded_square(u, v, 0.2):
        return None
    x, y = _rotate(u - 0.5, v - 0.5, -ANGLE)
    if _in_polygon(x, y, TAG_POLY) and (x - HOLE[0]) ** 2 + (y - HOLE[1]) ** 2 > HOLE[2] ** 2:
        return TAG
    return BG


def render(n):
    rows = []
    for py in range(n):
        row = bytearray([0])
        for px in range(n):
            acc = [0, 0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    c = pixel((px + (sx + 0.5) / SS) / n, (py + (sy + 0.5) / SS) / n)
                    if c:
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
                        acc[3] += 1
            hits = acc[3]
            if hits:
                row += bytes([round(acc[0] / hits), round(acc[1] / hits), round(acc[2] / hits), round(255 * hits / SS / SS)])
            else:
                row += bytes([0, 0, 0, 0])
        rows.append(bytes(row))
    return _png(n, b"".join(rows))


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png(n, raw):
    header = struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for n in (16, 32, 48, 128):
        path = OUT / f"icon-{n}.png"
        path.write_bytes(render(n))
        print(path, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
