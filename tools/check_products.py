#!/usr/bin/env python3
"""Контроль актуальности товаров сайта.

Проходит по всем товарам из front matter статей (content/*.md), запрашивает
карточки Яндекс Маркета, сохраняет снимок (data/snapshots/), формирует отчёт
(data/reports/) и, с флагом --apply, точечно обновляет front matter статей.

Подробности — в tools/README.md. Только стандартная библиотека + PyYAML.
"""
import argparse
import gzip
import http.cookiejar
import html as htmllib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
DATA = ROOT / "data"
SNAP_DIR = DATA / "snapshots"
REPORT_DIR = DATA / "reports"
BACKUP_DIR = DATA / "backups"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept-Encoding": "gzip",
}
REGION = "Москва (по умолчанию)"
PAUSE = (6.0, 10.0)      # пауза между запросами к Маркету, секунды
TIMEOUT = 40
CAPTCHA_RETRIES = 3         # повторов при капче
CAPTCHA_PAUSE = (45.0, 75.0)
RETRIES = 2              # повторов после первой неудачной попытки
PRICE_APPLY_THRESHOLD = 0.10
RATING_LOW = 4.3
RATING_DROP = 0.2

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


# ---------------------------------------------------------------- сеть

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


# cookie-jar: как у обычного браузера — Маркет реже показывает капчу при повторных запросах
_cookies = urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
_opener_follow = urllib.request.build_opener(_cookies)
_opener_nofollow = urllib.request.build_opener(_cookies, _NoRedirect)


class CaptchaError(Exception):
    pass
_last_request = [0.0]


def _polite_pause():
    """Выдерживает паузу 6–10 с между любыми двумя запросами к Маркету."""
    wait = _last_request[0] + random.uniform(*PAUSE) - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.time()


def http_get(url, follow=True):
    """-> (status, final_url, text, location). Бросает исключение при сетевой ошибке."""
    _polite_pause()
    req = urllib.request.Request(url, headers=HEADERS)
    opener = _opener_follow if follow else _opener_nofollow
    try:
        resp = opener.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        resp = e
    try:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        text = raw.decode("utf-8", errors="replace")
        status = getattr(resp, "status", None) or resp.code
        final = resp.geturl() if hasattr(resp, "geturl") else url
        if "showcaptcha" in final or 'class="CheckboxCaptcha' in text[:20000]:
            raise CaptchaError("Маркет показал капчу")
        return status, final, text, resp.headers.get("Location")
    finally:
        resp.close()


def with_retries(fn, *args, **kw):
    last = None
    captcha_left = CAPTCHA_RETRIES
    attempt = 0
    while True:
        try:
            return fn(*args, **kw)
        except CaptchaError as e:
            # капча — отдельный счётчик и длинная пауза, чтобы не злить Маркет
            last = e
            if captcha_left <= 0:
                raise
            captcha_left -= 1
            time.sleep(random.uniform(*CAPTCHA_PAUSE))
        except Exception as e:  # noqa: BLE001 — сетевые ошибки любого рода
            last = e
            if attempt >= RETRIES:
                raise
            attempt += 1
            time.sleep(random.uniform(*PAUSE))


# ---------------------------------------------------------------- разбор карточки

def card_id(url):
    m = re.search(r"/card/[^/?#]+/(\d+)", url or "")
    return m.group(1) if m else None


def _to_int(s):
    try:
        return int(re.sub(r"[^\d]", "", s))
    except ValueError:
        return None


def parse_bought(text):
    """«37 купили», «1,2 тыс. купили» -> int."""
    # только блок рейтинга ЭТОЙ карточки: «купили» у похожих товаров (сниппеты ниже)
    # в запасные варианты не берём, иначе подтянется чужое число
    m = re.search(r'data-auto="product-rating-description-item"[^>]*>.{0,500}?'
                  r'<span[^>]*>\s*([\d\s ,.]+?)\s*(тыс\.?)?\s*купил', text, re.S)
    if not m:
        return None
    num = m.group(1).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        val = float(num)
    except ValueError:
        return None
    return int(round(val * (1000 if m.group(2) else 1)))


def parse_card(text, pid):
    """Извлекает данные именно этой карточки (productId/sku = pid).

    Опора: JSON-LD Product с "sku":"<pid>" (оффер, цена, наличие, aggregateRating),
    запасные варианты — data-auto блоки карточки. Что не найдено — None.
    """
    res = {"title": None, "available": None, "price": None, "rating": None,
           "reviews": None, "bought": None, "source": None}
    # 1. JSON-LD Product с нужным sku. Весь фрагмент до следующего "review" —
    #    там offers и aggregateRating; ищем в окне после sku.
    for m in re.finditer(r'"sku":"%s"' % re.escape(pid), text):
        window = text[m.start(): m.start() + 4000]
        before = text[max(0, m.start() - 1500): m.start()]
        offer = re.search(r'"offers":\{[^{}]*\}', window)
        if not offer:
            continue
        off = offer.group(0)
        av = re.search(r'"availability":"([^"]+)"', off)
        pr = re.search(r'"price":"?([\d.]+)"?', off)
        res["source"] = "json-ld"
        if av:
            res["available"] = av.group(1).rsplit("/", 1)[-1] in ("InStock", "LimitedAvailability", "PreOrder")
        if pr:
            res["price"] = int(round(float(pr.group(1))))
        ag = re.search(r'"aggregateRating":\{[^{}]*\}', window)
        if ag:
            rv = re.search(r'"ratingValue":([\d.]+)', ag.group(0))
            rc = re.search(r'"ratingCount":(\d+)', ag.group(0))
            res["rating"] = float(rv.group(1)) if rv else None
            res["reviews"] = int(rc.group(1)) if rc else None
        nm = re.findall(r'"name":"((?:[^"\\]|\\.)*)"', before)
        if nm:
            try:
                res["title"] = json.loads('"%s"' % nm[-1])
            except ValueError:
                res["title"] = nm[-1]
        break
    # 2. запасные источники
    if res["title"] is None:
        m = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S)
        if m:
            res["title"] = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() or None
    if res["rating"] is None:
        m = re.search(r'data-auto="ratingValue"[^>]*>\s*([\d.,]+)', text)
        if m:
            res["rating"] = float(m.group(1).replace(",", "."))
    if res["reviews"] is None:
        m = re.search(r'data-auto="ratingCount"[^>]*>\s*\((\d+)\)', text)
        if m:
            res["reviews"] = int(m.group(1))
    if res["price"] is None:
        m = re.search(r'data-auto="snippet-price-current"[^>]*>(.{0,400}?)₽', text, re.S)
        if m:
            digits = re.sub(r"<[^>]+>", "", m.group(1))
            res["price"] = _to_int(digits)
            if res["price"] is not None and res["source"] is None:
                res["source"] = "html"
    res["bought"] = parse_bought(text)
    # 3. наличие: явные признаки «нет в продаже»
    if res["available"] is None:
        low = text.lower()
        if re.search(r"нет в продаже|нет в наличии|товар закончился|распродан", low):
            res["available"] = False
        elif 'data-auto="default-offer-buy-now-button"' in text or res["price"]:
            res["available"] = True
    elif res["available"] is True and res["price"] is None:
        res["available"] = None
    return res


def check_card(url):
    """Запрашивает карточку. -> dict с полями снимка + status."""
    pid = card_id(url)
    out = {"url": url, "http_status": None, "status": "error", "error": None,
           "title": None, "available": None, "price": None, "rating": None,
           "reviews": None, "bought": None, "source": None}
    try:
        status, final, text, _ = with_retries(http_get, url, True)
    except CaptchaError as e:
        out["status"] = "captcha"
        out["error"] = f"{e} (после {CAPTCHA_RETRIES} повторов с паузой)"
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    out["http_status"] = status
    if status == 404 or (card_id(final) != pid and "/card/" not in final) or \
            (card_id(final) is not None and card_id(final) != pid):
        out["status"] = "missing"
        out["error"] = f"карточка недоступна: HTTP {status}, итоговый URL {final[:120]}"
        return out
    if status != 200:
        out["error"] = f"HTTP {status}"
        return out
    out.update(parse_card(text, pid))
    out["status"] = "ok"
    if out["available"] is None and out["price"] is None and out["title"] is None:
        out["status"] = "parse_failed"
        out["error"] = "не удалось найти данные карточки в HTML"
    return out


def check_ref_link(link, expected_id):
    """Проверка партнёрской ссылки: редирект ведёт на карточку с тем же id.
    -> (ok: bool|None, detail)."""
    if not link:
        return None, "ссылка не задана"
    url = link
    try:
        for _ in range(5):
            status, _final, _t, loc = with_retries(http_get, url, False)
            if status in (301, 302, 303, 307, 308) and loc:
                url = urllib.request.urljoin(url, loc)
                if "/card/" in url:
                    got = card_id(url)
                    return got == expected_id, f"-> id {got}"
                continue
            return False, f"HTTP {status} без редиректа на карточку"
        return False, "слишком много редиректов"
    except Exception as e:  # noqa: BLE001
        return None, f"ошибка проверки: {type(e).__name__}: {e}"


# ---------------------------------------------------------------- статьи

def read_articles():
    """-> список {path, text, fm_span, meta} для статей с products."""
    arts = []
    for path in sorted(CONTENT.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = FRONT_RE.match(text)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1)) or {}
        if meta.get("products"):
            arts.append({"path": path, "text": text, "meta": meta})
    return arts


def fmt_rating(v):
    return f"{v:.1f}"


# ---------------------------------------------------------------- правка YAML

def edit_block(fm, label, changes):
    """Точечно правит значения в блоке товара `  label:` внутри front matter.

    changes: {ключ: значение | None}; None — удалить строку. Остальной текст
    не затрагивается. Возвращает новый fm.
    """
    lines = fm.split("\n")
    # границы секции products
    try:
        pstart = next(i for i, l in enumerate(lines) if re.match(r"^products:\s*$", l))
    except StopIteration:
        return fm
    start = None
    for i in range(pstart + 1, len(lines)):
        if re.match(r"^\S", lines[i]):
            break
        if re.match(r"^  %s:\s*$" % re.escape(label), lines[i]):
            start = i
            break
    if start is None:
        return fm
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^\S", lines[i]) or re.match(r"^  \S", lines[i]):
            end = i
            break
    for key, val in changes.items():
        idx = next((i for i in range(start + 1, end)
                    if re.match(r"^    %s:" % re.escape(key), lines[i])), None)
        if val is None:
            if idx is not None:
                del lines[idx]
                end -= 1
            continue
        new = f"    {key}: {val}"
        if idx is not None:
            lines[idx] = new
        else:
            # вставка: status — после name, остальные — после rating/price/последнего скалярного поля
            anchor = {"status": "name", "bought": "reviews", "reviews": "rating",
                      "rating": "price"}.get(key, "name")
            aidx = next((i for i in range(start + 1, end)
                         if re.match(r"^    %s:" % anchor, lines[i])), start)
            lines.insert(aidx + 1, new)
            end += 1
    return "\n".join(lines)


def set_updated(fm, today):
    if re.search(r"^updated:.*$", fm, re.M):
        return re.sub(r"^updated:.*$", f"updated: {today}", fm, count=1, flags=re.M)
    return re.sub(r"^(date:.*)$", r"\1\nupdated: " + today, fm, count=1, flags=re.M)


# ---------------------------------------------------------------- основной процесс

def latest_previous_snapshot(today):
    files = sorted(p for p in SNAP_DIR.glob("*.json") if p.stem < today) if SNAP_DIR.exists() else []
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def decide(entry, fm_prod, prev, price_is_sum=False):
    """Формирует решения по товару: что обновить автоматически, что требует решения."""
    auto, decide_ = {}, []
    r = entry["card"]
    label = entry["label"]
    fm_price = fm_prod.get("price")
    fm_rating = fm_prod.get("rating")
    unavailable_now = fm_prod.get("status") == "unavailable"

    if r["status"] == "missing":
        decide_.append(f"карточка пропала ({r['error']})")
    elif r["status"] != "ok":
        decide_.append(f"не удалось получить карточку: {r['error']}")
    else:
        if r["available"] is False:
            decide_.append("нет в продаже")
            if not unavailable_now:
                auto["status"] = "unavailable"
        elif r["available"] is True:
            if unavailable_now:
                auto["status"] = None  # вернулся в продажу
        else:
            decide_.append("не удалось определить наличие")
        if r["available"] is not False:
            if r["price"] is None:
                decide_.append("не удалось извлечь цену")
            elif price_is_sum:
                # в affiliate.json "price_is_sum": true — цена в статье равна сумме нескольких карточек
                if fm_price and abs(r["price"] - fm_price) / fm_price > PRICE_APPLY_THRESHOLD:
                    decide_.append("цена — сумма нескольких карточек, проверить вручную "
                                   f"(на этой карточке {r['price']}, в статье {fm_price})")
            elif fm_price and abs(r["price"] - fm_price) / fm_price > PRICE_APPLY_THRESHOLD:
                auto["price"] = r["price"]
            if r["rating"] is not None:
                if fm_rating is None or abs(r["rating"] - float(fm_rating)) > 1e-9:
                    auto["rating"] = fmt_rating(r["rating"])
                if r["reviews"] is not None and r["reviews"] != fm_prod.get("reviews"):
                    auto["reviews"] = r["reviews"]
            elif r["status"] == "ok" and fm_rating is not None:
                # на карточке нет блока оценок (или он не разобрался) — решает человек
                decide_.append(f"на Маркете нет оценок/не извлечён рейтинг (в статье {fm_rating})")
            if r["bought"] is not None and r["bought"] != fm_prod.get("bought"):
                auto["bought"] = r["bought"]
        # рейтинг
        if r["rating"] is not None:
            if r["rating"] < RATING_LOW:
                decide_.append(f"рейтинг {fmt_rating(r['rating'])} ниже {RATING_LOW}")
            for src, base in (("статье", fm_rating),
                              ("прошлом снимке", ((prev or {}).get(label) or {}).get("card", {}).get("rating"))):
                if base is not None and float(base) - r["rating"] >= RATING_DROP - 1e-9:
                    decide_.append(f"рейтинг упал с {fmt_rating(float(base))} до "
                                   f"{fmt_rating(r['rating'])} (по {src})")
                    break
    if entry["ref"]["ok"] is False:
        decide_.append(f"партнёрская ссылка ведёт не на ту карточку ({entry['ref']['detail']})")
    for k in ("aff", ):
        if entry.get(k) and entry[k]["ok"] is False:
            decide_.append(f"aff_url ведёт не на ту карточку ({entry[k]['detail']})")
    if entry["ref"]["ok"] is None and entry["ref"]["detail"] != "ссылка не задана":
        decide_.append(f"ссылку не удалось проверить ({entry['ref']['detail']})")
    return auto, decide_


def apply_changes(arts, plan, today):
    """plan: {путь_статьи: {label: changes}} -> правит файлы, делает бэкапы."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    done = []
    for art in arts:
        ch = plan.get(art["path"])
        if not ch:
            continue
        text = art["text"]
        m = FRONT_RE.match(text)
        fm = m.group(1)
        new_fm = fm
        for label, changes in ch.items():
            new_fm = edit_block(new_fm, label, changes)
        if new_fm == fm:
            continue
        new_fm = set_updated(new_fm, today)
        new_text = text[:m.start(1)] + new_fm + text[m.end(1):]
        shutil_backup = BACKUP_DIR / f"{art['path'].stem}.{stamp}.md"
        shutil_backup.write_text(text, encoding="utf-8", newline="")
        art["path"].write_text(new_text, encoding="utf-8", newline="")
        done.append(art["path"].name)
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="обновить front matter статей")
    ap.add_argument("--limit", type=int, help="проверить только первые N товаров")
    ap.add_argument("--only", action="append", help="только эта метка (можно несколько раз)")
    ap.add_argument("--no-links", action="store_true", help="не проверять партнёрские ссылки")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    today = date.today().isoformat()
    aff = json.loads((ROOT / "affiliate.json").read_text(encoding="utf-8"))
    arts = read_articles()

    # метка -> список (статья, данные товара)
    usage = {}
    for art in arts:
        for label, p in art["meta"]["products"].items():
            usage.setdefault(label, []).append((art, p))
    labels = list(usage)
    if args.only:
        labels = [l for l in labels if l in args.only]
    if args.limit:
        labels = labels[:args.limit]
    prev = latest_previous_snapshot(today)
    prev_items = (prev or {}).get("items", {})
    print(f"Товаров к проверке: {len(labels)}", flush=True)

    entries = []
    for n, label in enumerate(labels, 1):
        a = aff.get(label)
        if not a:
            entries.append({"label": label, "card": {"status": "error", "error": "нет в affiliate.json"},
                            "ref": {"ok": None, "detail": "нет в affiliate.json"}})
            continue
        exp_id = card_id(a.get("url"))
        card = check_card(a["url"])
        ref = {"ok": None, "detail": "ссылка не задана"}
        affc = None
        if not args.no_links:
            ok, det = check_ref_link(a.get("ref_link_no_erid"), exp_id)
            ref = {"ok": ok, "detail": det, "url": a.get("ref_link_no_erid")}
            if a.get("aff_url"):
                ok2, det2 = check_ref_link(a["aff_url"], exp_id)
                affc = {"ok": ok2, "detail": det2}
        entries.append({"label": label, "card_id": exp_id, "card": card, "ref": ref, "aff": affc})
        print(f"[{n}/{len(labels)}] {label}: {card['status']}, "
              f"доступен={card.get('available')}, цена={card.get('price')}, "
              f"рейтинг={card.get('rating')}, оценок={card.get('reviews')}, "
              f"купили={card.get('bought')}, ссылка={ref['ok']}", flush=True)

    # --- решения
    plan = {}
    rows = []
    auto_lines, decide_lines = [], []
    for e in entries:
        label = e["label"]
        if label not in usage:
            continue
        for art, fm_prod in usage[label]:
            auto, dec = decide(e, fm_prod, prev_items, (aff.get(label) or {}).get("price_is_sum", False))
            e.setdefault("decisions", []).extend(dec)
            if auto:
                plan.setdefault(art["path"], {})[label] = auto
            c = e["card"]
            pp = ((prev_items.get(label) or {}).get("card") or {}).get("price")
            rows.append((art["path"].name, label, fm_prod, c, pp, auto, dec))
            for k, v in auto.items():
                old = fm_prod.get(k)
                auto_lines.append(f"- `{label}` ({art['path'].name}): {k}: {old if old is not None else '—'} -> "
                                  f"{v if v is not None else 'снято'}")
            for d in dec:
                decide_lines.append(f"- `{label}` ({art['path'].name}): {d}")

    # --- снимок
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    snap = {"date": today, "time": datetime.now().isoformat(timespec="seconds"),
            "region": REGION, "applied": bool(args.apply),
            "items": {e["label"]: {k: v for k, v in e.items() if k != "label"} for e in entries}}
    snap_path = SNAP_DIR / f"{today}.json"
    if args.only or args.limit:  # частичный прогон — не затираем полный снимок
        if snap_path.exists():
            old = json.loads(snap_path.read_text(encoding="utf-8"))
            old["items"].update(snap["items"])
            old["time"] = snap["time"]
            snap = old
    snap_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- применение
    applied = []
    if args.apply and plan:
        applied = apply_changes(arts, plan, today)

    # --- отчёт
    def cell(v, suffix=""):
        return "—" if v is None else f"{v}{suffix}"

    md = [f"# Отчёт о проверке товаров — {today}", "",
          f"Регион: {REGION}. Время: {snap['time']}. Проверено товаров: {len(entries)}. "
          f"Режим: {'--apply (front matter обновлён)' if args.apply else 'только проверка (без --apply)'}.", "",
          "## Изменения по товарам", "",
          "| Статья | Метка | Цена в статье | Цена на Маркете | Прошлый снимок | Рейтинг: статья / Маркет | "
          "Оценок: статья / Маркет | Купили: статья / Маркет | Наличие | Ссылка |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    ref_by = {e["label"]: e["ref"] for e in entries}
    for fname, label, fp, c, pp, auto, dec in rows:
        av = {True: "в продаже", False: "нет в продаже", None: "?"}[c.get("available")]
        if c["status"] == "missing":
            av = "карточка пропала"
        elif c["status"] not in ("ok",):
            av = "ошибка"
        r = ref_by[label]
        rl = {True: "ок", False: "БИТАЯ", None: "—"}[r["ok"]]
        md.append(f"| {fname} | `{label}` | {cell(fp.get('price'), ' ₽')} | {cell(c.get('price'), ' ₽')} | "
                  f"{cell(pp, ' ₽')} | {cell(fp.get('rating'))} / {cell(c.get('rating'))} | "
                  f"{cell(fp.get('reviews'))} / {cell(c.get('reviews'))} | "
                  f"{cell(fp.get('bought'))} / {cell(c.get('bought'))} | {av} | {rl} |")
    md += ["", "## Обновлено автоматически" if args.apply else
           "## Было бы обновлено автоматически (при --apply)", ""]
    md += auto_lines or ["Нет изменений."]
    if args.apply:
        md += ["", "Изменены файлы: " + (", ".join(applied) if applied else "нет") +
               f". Бэкапы: `data/backups/`."]
    md += ["", "## Требует решения", ""]
    md += decide_lines or ["Ничего."]
    report_path = REPORT_DIR / (f"{today}-partial.md" if (args.only or args.limit) else f"{today}.md")
    report_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    ok = sum(1 for e in entries if e["card"]["status"] == "ok")
    n_dec = sum(1 for e in entries if e.get("decisions"))
    n_upd = sum(len(v) for v in plan.values())
    print("\nСводка:")
    print(f"  проверено товаров: {len(entries)} (карточка получена: {ok}, ошибок/пропали: {len(entries) - ok})")
    print(f"  {'обновлено' if args.apply else 'к обновлению (без --apply не записано)'}: {n_upd} товаров")
    print(f"  требует решения: {n_dec} товаров")
    print(f"  снимок: {snap_path}")
    print(f"  отчёт:  {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
