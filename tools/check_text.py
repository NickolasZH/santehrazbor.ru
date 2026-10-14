#!/usr/bin/env python3
"""Проверка цен в тексте статей и постов Дзена против цен товаров (только отчёт).

Ничего не правит. Печатает markdown-раздел в stdout; с --out FILE дописывает его в файл.
Правила и пороги — в tools/README.md. Только стандартная библиотека + PyYAML.
"""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
DZEN = ROOT.parent / "dzen"

TOLERANCE = 0.10        # допустимое расхождение цены в тексте и цены товара
STALE_DAYS = 14         # «цены на <дата>» старше — устарели
NAME_WINDOW = 120       # на сколько символов влево от цены ищем имя товара
MIN_PRICE = 1000        # цены меньше — аксессуары, не сравниваем
FM_KEYS = ("title", "description", "seo_title", "seo_description")
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]

SP = r"[ \u00a0\u202f]"
NUM = rf"\d{{1,3}}(?:{SP}\d{{3}})+|\d+"
PRICE_RE = re.compile(rf"(?P<num>{NUM})(?P<k>{SP}?тыс\.?)?{SP}?(?:₽|руб\w*|р\.)", re.I)
RANGE_RE = re.compile(
    rf"от{SP}(?P<a>{NUM}){SP}?(?:₽|руб\w*)?{SP}до{SP}(?P<b>{NUM}){SP}?(?:₽|руб\w*)", re.I)
DATE_RE = re.compile(
    rf"(?:на|состоянию на){SP}(?P<d>\d{{1,2}})"
    rf"(?:\.(?P<m>\d{{2}})(?:\.(?P<y>\d{{4}}))?|{SP}(?P<mn>{'|'.join(MONTHS)})(?:{SP}(?P<y2>\d{{4}}))?)",
    re.I)
FROM_RE = re.compile(
    rf"от{SP}(?P<a>{NUM}){SP}?(?:₽|руб\w*)?(?:{SP}до{SP}(?P<b>{NUM}))?{SP}?(?:₽|руб\w*)", re.I)
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def to_int(s):
    return int(re.sub(r"\D", "", s))


def norm(s):
    return re.sub(r"[\s\u00a0\u202f]+", " ", s.lower().replace("*", "").replace("ё", "е")).strip()


def pct(a, b):
    return abs(a - b) / b * 100 if b else 0.0


def esc(s):
    return s.replace("|", "\\|").replace("\n", " ")


def quote(line, start, end):
    """Цитата ≤ 80 символов вокруг найденного фрагмента."""
    a = max(0, start - 40)
    b = min(len(line), a + 80)
    a = max(0, min(a, b - 80))
    return ("…" if a else "") + line[a:b].strip() + ("…" if b < len(line) else "")


def load_articles():
    arts = []
    for path in sorted(CONTENT.glob("*.md")) + sorted((CONTENT / "calc").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = FM_RE.match(text)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1)) or {}
        prods = []
        for label, p in (meta.get("products") or {}).items():
            if p.get("name") and isinstance(p.get("price"), (int, float)):
                prods.append({"label": label, "name": str(p["name"]), "price": int(p["price"]),
                              "status": p.get("status")})
        arts.append({"path": path, "lines": text.split("\n"), "fm_lines": m.group(0).count("\n"),
                     "prods": prods, "meta": meta})
    return arts


def find_names(line, prods):
    """Вхождения имён товаров в строке: [(начало, конец, товар)], позиции совпадают с line."""
    low = line.lower().replace("ё", "е").replace("\u00a0", " ").replace("\u202f", " ")
    out = []
    for p in prods:
        n = norm(p["name"])
        if len(n) < 4:
            continue
        pat = re.escape(n).replace("\\ ", r"[\s*]+")
        for m in re.finditer(pat, low):
            out.append((m.start(), m.end(), p))
    # короткое имя внутри длинного (Atoll 1713 в Atoll 1713 GS) — оставляем длинное
    out = [o for o in out
           if not any(x is not o and x[0] <= o[0] and o[1] <= x[1] and (x[1] - x[0]) > (o[1] - o[0])
                      for x in out)]
    return sorted(out, key=lambda o: o[0])


def price_mentions(line):
    """Упоминания цен: (начало, конец, значение, хвост_диапазона, порог_«до»)."""
    res = []
    for m in PRICE_RE.finditer(line):
        v = to_int(m.group("num")) * (1000 if m.group("k") else 1)
        pre = line[max(0, m.start() - 12):m.start()].lower()
        is_range_tail = bool(re.search(r"\d[–—-]$", pre))
        is_upto = bool(re.search(r"(?:до|дешевле|менее|не дороже)\s*[~≈]?$", pre))
        res.append((m.start(), m.end(), v, is_range_tail, is_upto))
    return res


def not_a_price(line, start):
    """Число — не цена товара: разница («дороже на 3 400 ₽»), старая/зачёркнутая цена, скидка."""
    pre = line[max(0, start - 60):start].lower()
    return bool(re.search(r"(?:^|\s)на\s*[~≈]?$", pre) or re.search(r"стар|зачёркн|скидк|разниц", pre))


def mismatches_in_line(line, names, ments, price_of):
    """Цены, привязанные к ближайшему слева имени товара и расходящиеся с его ценой.
    -> [(цитата, в_тексте, текущая, %, имя)]. price_of(p, v) — эталонная цена товара."""
    res = []
    for s, e, v, tail, upto in ments:
        if v < MIN_PRICE or tail or upto or not_a_price(line, s):
            continue
        left = [n for n in names if n[1] <= s and s - n[1] <= NAME_WINDOW]
        if not left:
            continue
        n1, p = left[-1][1], left[-1][2]
        # другое предложение или другая цена между именем и ценой — привязка ненадёжна
        if re.search(r"[.!?;]\s", line[n1:s]) or any(n1 <= ms < s for ms, *_ in ments):
            continue
        ref = price_of(p, v)
        d = pct(v, ref)
        if d > TOLERANCE * 100:
            res.append((quote(line, s, e), v, ref, d, p["name"]))
    return res


def parse_date(m, today):
    try:
        if m.group("m"):
            mo = int(m.group("m"))
            y = int(m.group("y")) if m.group("y") else today.year
        else:
            mo = MONTHS.index(m.group("mn").lower()) + 1
            y = int(m.group("y2")) if m.group("y2") else today.year
        d = date(y, mo, int(m.group("d")))
        if d > today and not (m.group("y") or m.group("y2")):
            d = date(y - 1, mo, int(m.group("d")))
        return d
    except (ValueError, TypeError):
        return None


def body_lines(art):
    """-> (номер_строки, текст, последний_заголовок, товар_или_None).
    Для title/description, тела и строк внутри блока товара в products (товар — владелец блока)."""
    heading, in_products, owner = "", False, None
    by_label = {p["label"]: p for p in art["prods"]}
    for i, line in enumerate(art["lines"], 1):
        if i <= art["fm_lines"]:
            if re.match(r"\S", line):
                in_products = line.startswith("products:")
                owner = None
            elif in_products:
                m = re.match(r"  (\S+):\s*$", line)
                if m:
                    owner = by_label.get(m.group(1).strip("'\""))
                elif owner:
                    yield i, line, "", owner
                continue
            if any(line.startswith(k + ":") for k in FM_KEYS):
                yield i, line, "", None
            continue
        if re.match(r"#{2,3}\s", line):
            heading = line
        yield i, line, heading, None


def analyze(arts, today):
    price_rows, range_rows, thr_rows, date_rows = [], [], [], []
    for art in arts:
        prods = art["prods"]
        if not prods:
            continue
        lo, hi = min(p["price"] for p in prods), max(p["price"] for p in prods)
        fname = art["path"].name
        for i, line, heading, owner in body_lines(art):
            where = f"{fname}:{i}"
            if owner:
                # строка внутри карточки товара (pros/cons/who…): все цены относятся к этому товару
                for s_, e_, v, tail, upto in price_mentions(line):
                    if v >= MIN_PRICE and not tail and not upto and not not_a_price(line, s_) \
                            and "+" not in owner["name"] and pct(v, owner["price"]) > TOLERANCE * 100:
                        price_rows.append((where, quote(line, s_, e_), v, owner["price"],
                                           pct(v, owner["price"]), owner["name"]))
                continue
            names = find_names(line, prods)
            for q, v, ref, d, nm in mismatches_in_line(line, names, price_mentions(line), lambda p, v: p["price"]):
                price_rows.append((where, q, v, ref, d, nm))
            # диапазон «N моделей от X до Y ₽» — только в строках про набор моделей
            for m in RANGE_RE.finditer(line):
                if "модел" not in line.lower():
                    continue
                a, b = to_int(m.group("a")), to_int(m.group("b"))
                d = max(pct(a, lo), pct(b, hi))
                if d > TOLERANCE * 100:
                    range_rows.append((where, quote(line, m.start(), m.end()), f"{a}–{b}", f"{lo}–{hi}", d))
            # пороги «до N ₽»: товар в этой же строке дороже порога
            if i > art["fm_lines"] and names:
                low = line.lower()
                tabular = bool(re.match(r"\s*(\||[-*]\s)", line))
                limits = []  # (порог, позиция_в_строке или None для порога из заголовка)
                for m in re.finditer(rf"(?:до|дешевле){SP}(?P<n>{NUM}){SP}?(?:₽|руб)", low):
                    limits.append((to_int(m.group("n")), m.start()))
                for m in re.finditer(rf"(?:до|дешевле){SP}(?P<n>\d+){SP}?тыс", low):
                    limits.append((to_int(m.group("n")) * 1000, m.start()))
                # порог из заголовка раздела — только для строк таблиц и списков
                if tabular:
                    hm = re.search(rf"до{SP}({NUM}){SP}?₽", heading.lower())
                    if hm:
                        limits.append((to_int(hm.group(1)), None))
                for lim, pos in sorted(set(limits), key=lambda x: (x[0], x[1] or 0)):
                    for ns, ne, p in names:
                        # в прозе имя должно стоять сразу после порога (≤ 80 символов), иначе привязка ненадёжна
                        near = pos is None or 0 <= ns - pos <= 80
                        if near and p["price"] > lim:
                            thr_rows.append((where, quote(line, ns, ne), f"до {lim}",
                                             p["price"], pct(p["price"], lim), p["name"]))
            # устаревшие даты
            if re.search(r"цен|состоянию", line.lower()):
                for m in DATE_RE.finditer(line):
                    d = parse_date(m, today)
                    if d and (today - d).days > STALE_DAYS:
                        date_rows.append((where, quote(line, m.start(), m.end()), d.isoformat(),
                                          (today - d).days))
    return price_rows, range_rows, thr_rows, date_rows


def analyze_dzen(arts):
    by_name = {}
    for art in arts:
        for p in art["prods"]:
            by_name.setdefault(norm(p["name"]), []).append(p)
    all_prods = [p for ps in by_name.values() for p in ps]
    rows, seen = [], set()
    if not DZEN.is_dir():
        return rows

    def nearest(p, v):
        return min((q["price"] for q in by_name[norm(p["name"])]), key=lambda c: abs(c - v))

    for path in sorted(DZEN.glob("*.md")):
        for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            where = f"{path.name}:{i}"
            names = find_names(line, all_prods)
            for _, _, p in names:
                # снят с продажи хотя бы в одной статье и нигде не в продаже
                if all(q["status"] == "unavailable" for q in by_name[norm(p["name"])]) \
                        and (path.name, p["name"]) not in seen:
                    seen.add((path.name, p["name"]))
                    rows.append((where, quote(line, 0, len(line)), "—", "нет в продаже", None, p["name"]))
            for q, v, ref, d, nm in mismatches_in_line(line, names, price_mentions(line), nearest):
                rows.append((where, q, v, ref, d, nm))
    return rows


def analyze_fm_ranges(arts):
    """«от N ₽» / «от N до M ₽» в title/description/seo_*: N сверяем с минимальной ценой, M — с максимальной."""
    rows = []
    for art in arts:
        prods = art["prods"]
        if not prods:
            continue
        lo, hi = min(p["price"] for p in prods), max(p["price"] for p in prods)
        for key in FM_KEYS:
            val = str((art["meta"] or {}).get(key) or "")
            for m in FROM_RE.finditer(val):
                a = to_int(m.group("a"))
                b = to_int(m.group("b")) if m.group("b") else None
                d = pct(a, lo)
                if b is not None:
                    d = max(d, pct(b, hi))
                if d > TOLERANCE * 100:
                    rows.append((f"{art['path'].name}:{key}", quote(val, m.start(), m.end()),
                                 f"{a}–{b}" if b is not None else str(a),
                                 f"{lo}–{hi}" if b is not None else str(lo), d))
    return rows


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(esc(str(c)) for c in r) + " |")
    return out


def build_report(today=None):
    """-> (markdown, число_находок)."""
    today = today or date.today()
    arts = load_articles()
    price_rows, range_rows, thr_rows, date_rows = analyze(arts, today)
    dz = analyze_dzen(arts)
    fm_rows = analyze_fm_ranges(arts)
    n = len(price_rows) + len(range_rows) + len(thr_rows) + len(date_rows) + len(dz) + len(fm_rows)
    pc = lambda d: f"{d:.0f} %"
    md = ["## Проверка текста: цены в статьях и Дзене", "",
          f"Допуск {int(TOLERANCE * 100)} %, устаревшая дата — старше {STALE_DAYS} дн. "
          f"Находок: {n}. Скрипт ничего не правит.", ""]
    if price_rows:
        md += ["### Цена товара в тексте не совпадает", ""]
        md += table(["Статья:строка", "Цитата", "В тексте, ₽", "Текущая, ₽", "Расхождение", "Товар"],
                    [(w, q, v, c, pc(d), nm) for w, q, v, c, d, nm in price_rows]) + [""]
    if range_rows:
        md += ["### Диапазон цен не совпадает с товарами статьи", ""]
        md += table(["Статья:строка", "Цитата", "В тексте", "Товары статьи", "Расхождение"],
                    [(w, q, a, b, pc(d)) for w, q, a, b, d in range_rows]) + [""]
    if thr_rows:
        md += ["### Товар дороже порога «до N ₽»", ""]
        md += table(["Статья:строка", "Цитата", "Порог", "Текущая, ₽", "Превышение", "Товар"],
                    [(w, q, t, c, pc(d), nm) for w, q, t, c, d, nm in thr_rows]) + [""]
    if date_rows:
        md += ["### Устаревшие даты цен", ""]
        md += table(["Статья:строка", "Цитата", "Дата", "Дней назад"], date_rows) + [""]
    if fm_rows:
        md += ["### Цена «от N ₽» в title/description не совпадает с товарами статьи", ""]
        md += table(["Статья:поле", "Цитата", "В тексте", "Товары статьи", "Расхождение"],
                    [(w, q, a, b, pc(d)) for w, q, a, b, d in fm_rows]) + [""]
    if not (price_rows or range_rows or thr_rows or date_rows or fm_rows):
        md += ["В статьях расхождений нет.", ""]
    md += ["### Что поправить в Дзене", ""]
    if dz:
        md += table(["Пост:строка", "Цитата", "В тексте, ₽", "Текущая цена / статус", "Расхождение", "Товар"],
                    [(w, q, v, c, pc(d) if d is not None else "—", nm) for w, q, v, c, d, nm in dz]) + [""]
    else:
        md += ["Расхождений нет.", ""]
    return "\n".join(md), n


def main():
    ap = argparse.ArgumentParser(description="Проверка цен в тексте статей и Дзена (только отчёт)")
    ap.add_argument("--out", help="дописать отчёт в файл")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    md, n = build_report()
    print(md)
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            f.write("\n" + md + "\n")
    print(f"\nНаходок: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
