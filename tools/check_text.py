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
# «5,4 тыс.» / «5.4 тыс.»: десятичная дробь допустима только перед «тыс»
PRICE_RE = re.compile(rf"(?P<num>\d+[.,]\d+(?={SP}?тыс)|{NUM})(?P<k>{SP}?тыс\.?)?{SP}?(?:₽|руб\w*|р\.)", re.I)
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


def price_value(num, k):
    """Число из PRICE_RE -> рубли: «5,4» + «тыс» = 5400, «3 649» = 3649."""
    if k and re.fullmatch(r"\d+[.,]\d+", num):
        return round(float(num.replace(",", ".")) * 1000)
    return to_int(num) * (1000 if k else 1)


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
                              "status": p.get("status"), "rating": p.get("rating"),
                              "reviews": p.get("reviews"), "bought": p.get("bought"),
                              "warranty": p.get("warranty"), "material": p.get("material"),
                              "pros": p.get("pros"), "cons": p.get("cons")})
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
        v = price_value(m.group("num"), m.group("k"))
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


# --- числа отзывов / оценок / покупок / рейтинга -------------------------------------------------
CARD_KEYS = ("subtitle", "feature", "who", "reviews_text", "pros", "cons")
RATING_TOL = 0.05       # допуск рейтинга (абсолютный)
COUNT_TOL = 0.05        # допуск числа оценок/отзывов (и больше COUNT_MIN_DIFF шт.)
COUNT_MIN_DIFF = 2
BOUGHT_TOL = 0.10       # допуск числа покупок
APPROX_TOL = 0.10       # «около N» — допуск 10 %
APPROX = r"(?:около|почти|порядка|~|≈)"
COUNT_RE = re.compile(
    rf"(?P<pre>{APPROX}{SP}?)?(?P<n>{NUM}){SP}(?P<w>оцен\w*|отзыв\w*|покупк\w*|покупок|купили)", re.I)
BOUGHT_RE = re.compile(
    rf"купил\w*{SP}(?P<pre>{APPROX}{SP}?)?(?P<n>{NUM})(?!{SP}?(?:₽|руб|тыс))", re.I)
RATING_RES = (
    re.compile(r"рейтинг\w*[  ]*[—:-]?[  ]*(?P<r>\d[.,]\d)(?![\d.,]*\s*(?:[–—-]|до\b))", re.I),
    re.compile(r"(?P<r>\d[.,]\d)[  ]*из[  ]*5", re.I),
    re.compile(r"★[  ]*(?P<r>\d[.,]\d)"),
)
THRESHOLD_PRE = re.compile(
    r"(?:от|до|более|свыше|минимум|больше|менее|не менее|не более|всего|только)\s*[~≈]?$", re.I)


def stat_mentions(line):
    """Упоминания рейтинга и счётчиков: [(начало, конец, вид, значение, приблизительно)].
    вид: rating | reviews (оценки/отзывы) | bought (покупки)."""
    res = set()
    for rx in RATING_RES:
        for m in rx.finditer(line):
            res.add((m.start(), m.end(), "rating", float(m.group("r").replace(",", ".")), False))
    for m in COUNT_RE.finditer(line):
        pre = line[max(0, m.start() - 14):m.start()].lower()
        if THRESHOLD_PRE.search(pre) or re.search(r"\d[–—-]$", pre):
            continue  # пороги и диапазоны («от 5 отзывов») — не заявление о числе
        w = m.group("w").lower()
        kind = "reviews" if w.startswith("оцен") else "reviews_t" if w.startswith("отзыв") else "bought"
        res.add((m.start(), m.end(), kind, to_int(m.group("n")), bool(m.group("pre"))))
    for m in BOUGHT_RE.finditer(line):
        res.add((m.start(), m.end(), "bought", to_int(m.group("n")), bool(m.group("pre"))))
    return sorted(res)


def stat_mismatch(kind, v, approx, p):
    """-> (в_карточке, расхождение) если число расходится с карточкой товара p, иначе None."""
    # в карточке нет отдельного поля для текстовых отзывов: их не больше, чем оценок (reviews),
    # поэтому «N отзывов» — находка только если N больше числа оценок
    ref = p.get("reviews" if kind == "reviews_t" else kind)
    if not isinstance(ref, (int, float)):
        return None
    if kind == "reviews_t" and v <= ref:
        return None
    if kind == "rating":
        return (ref, f"{abs(v - ref):.2f}") if abs(v - ref) > RATING_TOL + 1e-9 else None
    tol = APPROX_TOL if approx else (BOUGHT_TOL if kind == "bought" else COUNT_TOL)
    if abs(v - ref) / max(ref, 1) > tol and (kind == "bought" or abs(v - ref) > COUNT_MIN_DIFF):
        return (ref, f"{pct(v, ref):.0f} %")
    return None


# --- сравнительные утверждения ------------------------------------------------------------------
CHEAP_RE = re.compile(
    r"самы[йе]\s+(?:дешёв|дешев|бюджетн)\w+|самая\s+(?:низкая\s+цена|доступн\w+|дешёв\w+|дешев\w+)"
    r"|дешевле\s+всех", re.I)
POPULAR_RE = re.compile(
    r"самы[йе]\s+(?:популярн|покупаем)\w+|самая\s+популярн\w+"
    r"|больше\s+всего\s+(?P<what>отзыв\w*|оцен\w*|покупок|покупател\w+)", re.I)


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


def price_bounds(prods):
    """(min, max) цен товаров в продаже; товары со status: unavailable не считаются. Нет таких — (None, None)."""
    prices = [p["price"] for p in prods if p["status"] != "unavailable"]
    return (min(prices), max(prices)) if prices else (None, None)


def analyze(arts, today):
    price_rows, range_rows, thr_rows, date_rows = [], [], [], []
    for art in arts:
        prods = art["prods"]
        if not prods:
            continue
        lo, hi = price_bounds(prods)
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
                if "модел" not in line.lower() or lo is None:
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
    date_rows += analyze_prices_checked(arts, today)
    return price_rows, range_rows, thr_rows, date_rows


def analyze_prices_checked(arts, today):
    """Поле prices_checked во front matter: нет или старше STALE_DAYS — находка.
    Текст берёт дату цен из него ({{prices_date}}), поэтому устаревшее поле = устаревшие цены на сайте."""
    rows = []
    for art in arts:
        if not art["prods"]:
            continue
        where = f"{art['path'].name}:prices_checked"
        raw = art["meta"].get("prices_checked")
        if not raw:
            rows.append((where, "поле prices_checked не задано", "—", "—"))
            continue
        try:
            d = raw if isinstance(raw, date) else date.fromisoformat(str(raw))
        except ValueError:
            rows.append((where, f"prices_checked: {raw}", "не дата", "—"))
            continue
        if (today - d).days > STALE_DAYS:
            rows.append((where, f"prices_checked: {d.isoformat()}", d.isoformat(), (today - d).days))
    return rows


def pick_subject(line, pos, names, owner):
    """Товар, к которому относится утверждение в позиции pos: владелец карточки, иначе ближайшее имя
    в том же предложении (слева приоритетнее) в пределах NAME_WINDOW."""
    if owner:
        return owner
    best = None
    for ns, ne, p in names:
        gap = pos - ne if ne <= pos else ns - pos
        seg = line[ne:pos] if ne <= pos else line[pos:ns]
        if gap > NAME_WINDOW or re.search(r"[.!?;]\s", seg):
            continue
        key = (0 if ne <= pos else 1, gap)
        if best is None or key < best[0]:
            best = (key, p)
    return best[1] if best else None


def analyze_stats(arts):
    """-> (строки расхождений чисел, строки сравнительных утверждений)."""
    stat_rows, cmp_rows = [], []
    labels = {"rating": "рейтинг", "reviews": "оценки", "reviews_t": "отзывы (больше оценок)", "bought": "покупки"}
    for art in arts:
        prods = art["prods"]
        if not prods:
            continue
        fname = art["path"].name
        # «самый дешёвый» — только среди товаров в продаже
        on_sale = [p for p in prods if p["status"] != "unavailable"]
        lo = min(on_sale, key=lambda p: p["price"]) if on_sale else None
        with_b = [p for p in prods if isinstance(p.get("bought"), (int, float))]
        with_r = [p for p in prods if isinstance(p.get("reviews"), (int, float))]
        cur_key = None
        for i, line, heading, owner in body_lines(art):
            where = f"{fname}:{i}"
            if owner:
                km = re.match(r"    (\w+):", line)
                if km:
                    cur_key = km.group(1)
                if cur_key not in CARD_KEYS or "+" in owner["name"]:
                    continue
                names = []
            else:
                cur_key = None
                names = find_names(line, prods)
                if not names:
                    continue
            ments = stat_mentions(line)
            for s_, e_, kind, v, approx in ments:
                p = owner
                if not owner:
                    left = [n for n in names if n[1] <= s_ and s_ - n[1] <= NAME_WINDOW]
                    if not left:
                        continue
                    n1, p = left[-1][1], left[-1][2]
                    # другое предложение или другое число между именем и этим числом — привязка ненадёжна
                    if re.search(r"[.!?;]\s", line[n1:s_]) or any(n1 <= ms < s_ for ms, *_ in ments):
                        continue
                bad = stat_mismatch(kind, v, approx, p)
                if bad:
                    shown = f"{v:g}" if kind == "rating" else str(v)
                    stat_rows.append((where, quote(line, s_, e_), f"{labels[kind]}: {shown}",
                                      f"{bad[0]:g} (расх. {bad[1]})", p["name"]))
            for rx, which in ((CHEAP_RE, "cheap"), (POPULAR_RE, "popular")):
                for m in rx.finditer(line):
                    p = pick_subject(line, m.start(), names, owner)
                    if not p or "+" in p["name"]:
                        continue
                    if which == "cheap":
                        if lo and p["price"] > lo["price"]:
                            cmp_rows.append((where, quote(line, m.start(), m.end()),
                                             f"{p['name']}: {p['price']} ₽",
                                             f"дешевле всех — {lo['name']}: {lo['price']} ₽", p["name"]))
                        continue
                    what = (m.group("what") or "").lower()
                    by_rev = what.startswith(("отзыв", "оцен"))
                    pool, field = (with_r, "reviews") if by_rev or not with_b else (with_b, "bought")
                    if not pool or not isinstance(p.get(field), (int, float)):
                        continue
                    top = max(pool, key=lambda q: q[field])
                    if p[field] < top[field]:
                        cmp_rows.append((where, quote(line, m.start(), m.end()),
                                         f"{p['name']}: {field} {p[field]}",
                                         f"больше всего — {top['name']}: {top[field]}", p["name"]))
    return stat_rows, cmp_rows


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
        lo, hi = price_bounds(prods)
        if lo is None:
            continue
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


def _norm_items(items):
    return {norm(str(x)) for x in (items or [])}


def analyze_cross_article(arts):
    """Один id товара в нескольких статьях: данные должны совпадать.
    -> (строки расхождений полей, строки предупреждений по pros/cons).
    Строка: (товар, поле, статья_A, значение_A, статья_B, значение_B)."""
    by_label = {}
    for art in arts:
        for p in art["prods"]:
            by_label.setdefault(p["label"], []).append((art["path"].name, p))
    rows, warns = [], []
    for label, lst in by_label.items():
        if len(lst) < 2:
            continue
        fa, pa = lst[0]
        for fb, pb in lst[1:]:
            def add(field, va, vb):
                rows.append((label, field, fa, va, fb, vb))
            if pct(pa["price"], pb["price"]) > 3:
                add("price", pa["price"], pb["price"])
            ra, rb = pa.get("rating"), pb.get("rating")
            if ra is not None and rb is not None and abs(float(ra) - float(rb)) > 1e-9:
                add("rating", ra, rb)
            for k in ("reviews", "bought"):
                va, vb = pa.get(k), pb.get(k)
                if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                    if abs(va - vb) > 2 and (k == "reviews" or pct(va, vb) > 5):
                        add(k, va, vb)
            for k in ("warranty", "material"):
                va, vb = pa.get(k), pb.get(k)
                if va and vb and norm(str(va)) != norm(str(vb)):
                    add(k, va, vb)
            for k in ("pros", "cons"):
                sa, sb = _norm_items(pa.get(k)), _norm_items(pb.get(k))
                diff = sa ^ sb
                # наборы почти совпадают (общих ≥ 2), но отличаются одним-двумя пунктами
                if diff and len(sa & sb) >= 2 and len(diff) <= 2:
                    warns.append((label, k, fa, "; ".join(sorted(sa - sb)) or "—",
                                  fb, "; ".join(sorted(sb - sa)) or "—"))
    return rows, warns


REREAD_WORDS = re.compile(r"цен|дорог|дешев|₽|руб|оценк|рейтинг|покуп", re.I)


def product_lines(arts, label):
    """Все строки всех статей, где упомянут товар: [(статья:строка, текст)].
    Привязка: id в шорткоде ([[product:id]], [[minitable:...]]), имя товара (find_names),
    строки внутри его карточки во front matter — только про цену/оценки."""
    out = []
    code_re = re.compile(r"\[\[(?:product|minitable):(?:[^\]]*[:,])?" + re.escape(label) + r"(?![\w-])[^\]]*\]\]")
    for art in arts:
        mine = [p for p in art["prods"] if p["label"] == label]
        if not mine:
            continue
        fname = art["path"].name
        for i, line, heading, owner in body_lines(art):
            if owner is not None:
                if owner["label"] == label and REREAD_WORDS.search(line):
                    out.append((f"{fname}:{i}", line.strip()))
            elif i > art["fm_lines"] and (code_re.search(line) or find_names(line, mine)):
                out.append((f"{fname}:{i}", line.strip()))
    return out


def reread_rows(arts, changes):
    """changes: [{label, name, what}] -> строки (товар, что изменилось, статья:строка, текст ≤140)."""
    rows = []
    for ch in changes:
        for where, text in product_lines(arts, ch["label"]):
            rows.append((ch["name"], ch["what"], where, text[:140] + ("…" if len(text) > 140 else "")))
    return rows


def reread_section(changes):
    """Раздел отчёта «Перечитать после изменения цен» (markdown-строки). Вызывает check_products."""
    md = ["## Перечитать после изменения цен", ""]
    if not changes:
        return md + ["Цены (> 10 %), рейтинги и число оценок заметно не менялись.", ""]
    rows = reread_rows(load_articles(), changes)
    if not rows:
        return md + ["Изменения есть, но упоминаний товаров в текстах не найдено.", ""]
    md += ["Товары, у которых в этом прогоне цена изменилась > 10 % или заметно изменились рейтинг/оценки. "
           "Строки, где они упомянуты (по id в шорткоде и по имени):", ""]
    return md + table(["Товар", "Что изменилось", "Статья:строка", "Строка"], rows) + [""]


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
    stat_rows, cmp_rows = analyze_stats(arts)
    cross_rows, cross_warns = analyze_cross_article(arts)
    n = len(cross_rows) + len(cross_warns) + len(stat_rows) + len(cmp_rows) + len(price_rows) + len(range_rows) + len(thr_rows) + len(date_rows) + len(dz) + len(fm_rows)
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
    if stat_rows:
        md += ["### Числа отзывов, оценок, покупок и рейтинга не совпадают с карточкой", ""]
        md += table(["Статья:строка", "Цитата", "В тексте", "В карточке", "Товар"], stat_rows) + [""]
    if cmp_rows:
        md += ["### Сравнительные утверждения (предупреждение, возможны ложные срабатывания)", ""]
        md += table(["Статья:строка", "Цитата", "Товар из текста", "На самом деле", "Товар"], cmp_rows) + [""]
    if cross_rows:
        md += ["### Товар в нескольких статьях: данные расходятся", ""]
        md += table(["Товар", "Поле", "Статья A", "Значение A", "Статья B", "Значение B"], cross_rows) + [""]
    if cross_warns:
        md += ["### Товар в нескольких статьях: pros/cons почти совпадают, но отличаются (предупреждение)", ""]
        md += table(["Товар", "Список", "Статья A", "Только в A", "Статья B", "Только в B"], cross_warns) + [""]
    if not (cross_rows or cross_warns or stat_rows or cmp_rows or price_rows or range_rows or thr_rows or date_rows or fm_rows):
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
