#!/usr/bin/env python3
"""Генерирует значок сайта в static/: favicon.svg, favicon.ico, favicon-32.png, apple-touch-icon.png.

Дизайн: скруглённый квадрат цвета #0e7490 и белая капля по центру.
Запуск: python tools/make_favicon.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "static"
COLOR = (14, 116, 144, 255)
WHITE = (255, 255, 255, 255)

# Капля в системе 64x64: острая вершина сверху, круглое дно.
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
    <rect width="64" height="64" rx="14" fill="#0e7490"/>
    <path d="M32 11 C32 11 18 27 18 38 A14 14 0 0 0 46 38 C46 27 32 11 32 11 Z" fill="#fff"/>
</svg>
"""


def drop_points(n=120):
    """Контур капли (в координатах 64x64), совпадающий с SVG-путём."""
    pts = []
    cx, cy, r = 32.0, 38.0, 14.0
    # дуга дна: от (18,38) через низ до (46,38)
    for i in range(n + 1):
        a = math.pi - math.pi * i / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    # правая сторона вверх к вершине (кубическая Безье)
    def bez(p0, p1, p2, p3, t):
        u = 1 - t
        return tuple(u**3 * a + 3 * u**2 * t * b + 3 * u * t**2 * c + t**3 * d
                     for a, b, c, d in zip(p0, p1, p2, p3))
    for i in range(1, n + 1):
        pts.append(bez((46, 38), (46, 27), (32, 11), (32, 11), i / n))
    for i in range(1, n + 1):
        pts.append(bez((32, 11), (32, 11), (18, 27), (18, 38), i / n))
    return pts


def render(size):
    k = 8  # суперсэмплинг для сглаживания
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=14 * s / 64, fill=COLOR)
    d.polygon([(x * s / 64, y * s / 64) for x, y in drop_points()], fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main():
    STATIC.mkdir(exist_ok=True)
    (STATIC / "favicon.svg").write_text(SVG, encoding="utf-8")
    render(32).save(STATIC / "favicon-32.png")
    render(180).save(STATIC / "apple-touch-icon.png")
    render(256).save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("Готово: favicon.svg, favicon.ico, favicon-32.png, apple-touch-icon.png")


if __name__ == "__main__":
    main()
