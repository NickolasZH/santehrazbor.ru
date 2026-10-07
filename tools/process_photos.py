"""Обработка фото автора: поворот по EXIF, кроп, ресайз до 1000px, JPEG без метаданных.
Исходники не изменяются. Запуск: python tools/process_photos.py"""
from pathlib import Path
from PIL import Image, ImageOps

SRC = Path(r"C:\Users\nicko\.claude\uploads\05295037-62fb-4624-99f5-573f91daf0bb")
OUT = Path(__file__).resolve().parent.parent / "static" / "img"
MAX_W = 1000

# (исходник, результат, кроп left/top/right/bottom в координатах 1500x2000)
JOBS = [
    ("3872bb15-image.jpg", "kitchen-flexible-spout.jpg", (150, 150, 1380, 1800)),
    ("f8f095a4-image.jpg", "bath-mixer-limescale.jpg", (0, 300, 1180, 1200)),
    ("f8b9a8bd-image.jpg", "basin-mixer-matte.jpg", (350, 450, 1250, 1450)),
]

OUT.mkdir(parents=True, exist_ok=True)
for src, dst, box in JOBS:
    im = ImageOps.exif_transpose(Image.open(SRC / src)).convert("RGB")
    print(src, im.size)
    k = im.width / 1500  # реальный размер может отличаться от 1500x2000
    im = im.crop(tuple(round(v * k) for v in box))
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    clean = Image.new("RGB", im.size)  # новое изображение — без EXIF
    clean.paste(im)
    clean.save(OUT / dst, "JPEG", quality=80, progressive=True, optimize=True)
    print(dst, clean.size, (OUT / dst).stat().st_size)
