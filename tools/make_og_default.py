"""Генерирует общую og-карточку static/img/og/default.png (1280x720) в стиле обложек Дзена.
Запуск: .venv/bin/python tools/make_og_default.py [ПАПКА_ШРИФТОВ] (из папки site).
Нужны шрифты segoeui.ttf и segoeuib.ttf; без аргумента берётся C:/Windows/Fonts, если она есть."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "static" / "img" / "og" / "default.png"
# Папка со шрифтами Segoe UI: аргумент или системная папка Windows
FONTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("C:/Windows/Fonts")
for _name in ("segoeui.ttf", "segoeuib.ttf"):
    if not (FONTS / _name).is_file():
        sys.exit(f"Не найден шрифт {FONTS / _name}. Укажите папку со шрифтами: "
                 ".venv/bin/python tools/make_og_default.py ПАПКА_ШРИФТОВ")
TEAL, BG, FOOT = (16, 117, 145), (243, 246, 250), (71, 85, 105)

img = Image.new("RGB", (1280, 720), BG)
d = ImageDraw.Draw(img)
d.rectangle([0, 0, 1280, 230], fill=TEAL)
bold = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 84)
reg = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 34)
d.text((64, 50), "Сантехразбор", font=bold, fill="white")
d.text((66, 158), "Что внутри смесителей и душей: корпус, картридж, гарантия, отзывы",
       font=ImageFont.truetype(str(FONTS / "segoeui.ttf"), 32), fill=(214, 235, 242))
# три плашки-тезисы
items = ["Корпус", "Картридж", "Гарантия", "Отзывы"]
x = 62
for t in items:
    d.rounded_rectangle([x, 330, x + 268, 500], radius=26, fill="white", outline=TEAL, width=5)
    w = d.textlength(t, font=ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 40))
    d.text((x + (268 - w) / 2, 385), t, font=ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 40), fill=(30, 41, 59))
    x += 296
foot = "santehrazbor.ru — разбираем сантехнику изнутри"
w = d.textlength(foot, font=reg)
d.text(((1280 - w) / 2, 620), foot, font=reg, fill=FOOT)
OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, optimize=True)
print(OUT)
