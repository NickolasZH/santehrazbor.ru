#!/usr/bin/env python3
"""Статический генератор сайта: content/*.md -> docs/ (GitHub Pages).

Запуск: python build.py
"""
import hashlib
import json
import re
import shutil
import sys
from datetime import date, datetime
from html import escape as html_escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image
import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).parent / "tools"))
import calc_plitka_ref as plitka  # Python-эталон формул калькулятора плитки
import calc_zatirka_ref as zatirka  # Python-эталон формул калькулятора затирки
import calc_vodonagrevatel_ref as vodonagrevatel  # Python-эталон формул калькулятора водонагревателя

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
DOCS = ROOT / "docs"

AFF_REL = "sponsored nofollow noopener"


def ad_mark_inline_html(ad_label):
    """Рекламная метка для ссылок внутри абзаца: только phrasing-content (<details> в <p> недопустим)."""
    if not ad_label:
        return ""
    info = ad_label[len("Реклама. "):] if ad_label.startswith("Реклама. ") else ad_label
    return ('<span class="ad-mark ad-mark-inline" tabindex="0" role="button">Реклама <span aria-hidden="true">ⓘ</span>'
            f'<span class="ad-mark-info">: {html_escape(info)}</span></span>')


def ad_mark_html(ad_label):
    """Компактная рекламная метка: «Реклама ⓘ» видна всегда, сведения — в раскрывающемся <details>."""
    if not ad_label:
        return ""
    info = ad_label[len("Реклама. "):] if ad_label.startswith("Реклама. ") else ad_label
    return ('<details class="ad-mark"><summary>Реклама <span aria-hidden="true">ⓘ</span></summary>'
            f'<span class="ad-mark-info">{html_escape(info)}</span></details>')


def fail(msg):
    sys.exit(f"ОШИБКА СБОРКИ: {msg}")


_asset_hashes = {}


def asset_hash(rel_path):
    """Первые 8 символов md5 файла из static/ — метка версии против устаревшего кэша браузера."""
    if rel_path not in _asset_hashes:
        _asset_hashes[rel_path] = hashlib.md5((STATIC / rel_path).read_bytes()).hexdigest()[:8]
    return _asset_hashes[rel_path]


def load_json(name):
    with open(ROOT / name, encoding="utf-8") as f:
        return json.load(f)


def build_aff_url(label, data):
    """aff_url, если задан, иначе url; erid добавляется в query, если его там нет."""
    url = data.get("aff_url") or data.get("url")
    if not url:
        fail(f"для метки AFF:{label} не задан ни url, ни aff_url в affiliate.json")
    erid = data.get("erid")
    if erid and data.get("aff_url"):
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        if not any(k == "erid" for k, _ in query):
            query.append(("erid", erid))
            url = urlunsplit(parts._replace(query=urlencode(query)))
    return url


def split_front_matter(text, path):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        fail(f"{path.name}: нет YAML front matter")
    return yaml.safe_load(m.group(1)), m.group(2)


def cover_size(fname):
    """Ширина и высота обложки карточки: viewBox для svg, реальный размер для растра."""
    path = STATIC / "img" / fname
    if path.suffix.lower() == ".svg":
        vb = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"',
                       path.read_text(encoding="utf-8"))
        if not vb:
            fail(f"обложка {fname}: нет viewBox")
        return tuple(int(float(x)) for x in vb.groups())
    with Image.open(path) as im:
        return im.size


def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def iso_dt(v):
    # Для JSON-LD: полная дата-время с часовым поясом Москвы (время фиксированное)
    return f"{to_date(v).isoformat()}T09:00:00+03:00"


RU_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря"]


def ru_date(d):
    return f"{d.day} {RU_MONTHS[d.month - 1]} {d.year}"


def strip_tags(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def parse_faq(body_md):
    """Раздел «Частые вопросы»: вопрос — строка/абзац целиком в **...**, ответ — далее."""
    m = re.search(r"^##\s+Частые вопросы[^\n]*\n(.*?)(?=^##\s|\Z)", body_md, re.S | re.M)
    if not m:
        return []
    faq = []
    # режем на блоки-абзацы и строки; вопрос начинается со строки "**...**"
    cur_q, cur_a = None, []
    for line in m.group(1).splitlines():
        s = line.strip()
        q = re.fullmatch(r"\*\*(.+?)\*\*", s)
        if q:
            if cur_q and cur_a:
                faq.append((cur_q, " ".join(cur_a)))
            cur_q, cur_a = q.group(1), []
        elif s in ("", "---"):
            continue
        elif s.startswith("*") and s.endswith("*") and cur_q and cur_a:
            continue  # финальная курсивная сноска
        elif cur_q:
            cur_a.append(s)
    if cur_q and cur_a:
        faq.append((cur_q, " ".join(cur_a)))
    out = []
    for q, a in faq:
        a_html = markdown.markdown(a)
        out.append({"q": q, "a": strip_tags(a_html)})
    return out


TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}


def slugify_ru(value, separator="-"):
    """Транслитерация кириллицы для id заголовков (используется расширением toc)."""
    s = "".join(TRANSLIT.get(ch, ch) for ch in value.lower())
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", separator, s).strip(separator)
    return s or "section"


NBSP = " "


def fmt_int(n):
    """12600 -> '12 600' с неразрывным пробелом."""
    return f"{int(n):,}".replace(",", NBSP)


def rub(n, approx=True):
    return ("~" if approx else "") + fmt_int(n) + NBSP + "₽"


def plural(n, forms):
    """plural(52, ('оценка', 'оценки', 'оценок'))"""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def count_word(n, forms):
    return f"{n}{NBSP}{plural(n, forms)}"


def nbsp_text(html):
    """В текстовых узлах HTML: разделитель тысяч и пробел перед ₽ — неразрывные."""
    parts = re.split(r"(<[^>]+>)", html)
    for i in range(0, len(parts), 2):
        s = parts[i]
        s = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", NBSP, s)
        s = re.sub(r"(?<=\d) (?=₽)", NBSP, s)
        parts[i] = s
    return "".join(parts)


def md_inline(text):
    """Inline-markdown (жирный и т.п.) без обёртки <p>."""
    from markupsafe import Markup
    html = markdown.markdown(str(text))
    html = re.sub(r"^<p>(.*)</p>$", r"\1", html, flags=re.S)
    return Markup(nbsp_text(html))


def badge_class(text):
    t = (text or "").lower()
    if "лучш" in t:
        return "best"
    if "бюджет" in t:
        return "budget"
    if "премиум" in t:
        return "premium"
    return "other"


SHORTCODE_RE = re.compile(r"^\[\[\s*([^\]\n]+?)\s*\]\][ \t]*$", re.M)


def build_products(meta, aff, ctx_name):
    """Список товаров статьи из front matter с готовыми ссылками."""
    raw = meta.get("products") or {}
    products = []
    for i, (label, p) in enumerate(raw.items(), 1):
        if label not in aff:
            fail(f"{ctx_name}: товар «{label}» из products не найден в affiliate.json")
        for key in ("name", "price", "feature"):
            if key not in p:
                fail(f"{ctx_name}: у товара {label} нет поля {key}")
        data = aff[label]
        products.append({
            **p, "label": label, "n": i,
            "href": build_aff_url(label, data), "rel": AFF_REL,
            "ad_label": data.get("ad_label") or "",
            "ad_mark_html": ad_mark_html(data.get("ad_label")), "market_url": data.get("url") or "",
            "badge_class": badge_class(p.get("badge")),
        })
    picks = meta.get("picks") or []
    by_label = {p["label"]: p for p in products}
    for lab in picks:
        if lab not in by_label:
            fail(f"{ctx_name}: в picks указана неизвестная метка «{lab}» (нет в products)")
    return products, [by_label[lab] for lab in picks]


def apply_prices_date(body, meta, name):
    """Подставляет {{prices_date}} («19.10.2026») и {{prices_date_text}} («19 октября 2026»)
    из поля prices_checked front matter. Нет поля — сборка падает с понятной ошибкой."""
    if "{{prices_date" not in body:
        return body
    if not meta.get("prices_checked"):
        fail(f"{name}: в тексте плейсхолдер {{{{prices_date}}}}, а в front matter нет поля prices_checked (YYYY-MM-DD)")
    d = to_date(meta["prices_checked"])
    return (body.replace("{{prices_date_text}}", ru_date(d))
                .replace("{{prices_date}}", d.strftime("%d.%m.%Y")))


def render_markdown(body_md, aff, used_labels, env, article_ctx):
    """markdown -> HTML со шорткодами [[picks]], [[compare]], [[product:метка]], [[minitable:метки]], [[toc]]."""
    name = article_ctx["name"]
    products = article_ctx["products"]
    by_label = {p["label"]: p for p in products}
    shortcodes = []

    def sc_repl(m):
        code = m.group(1)
        if code in ("picks", "compare", "toc"):
            if code in ("picks", "compare") and not products:
                fail(f"{name}: шорткод [[{code}]] без поля products в front matter")
            if code == "picks" and not article_ctx["picks"]:
                fail(f"{name}: шорткод [[picks]] без поля picks в front matter")
        elif code.startswith("photo:"):
            fname, sep, cap = code.split(":", 1)[1].partition("|")
            if not sep or not cap.strip():
                fail(f"{name}: шорткод [[photo:файл|подпись]] — нет подписи ({code[:40]})")
            if not (STATIC / "img" / fname.strip()).is_file():
                fail(f"{name}: фото static/img/{fname.strip()} не найдено")
        elif code.startswith("scheme:"):
            fname, sep, cap = code.split(":", 1)[1].partition("|")
            if not sep or not cap.strip():
                fail(f"{name}: шорткод [[scheme:файл.svg|подпись]] — нет подписи ({code[:40]})")
            if not (STATIC / "img" / fname.strip()).is_file():
                fail(f"{name}: схема static/img/{fname.strip()} не найдена")
        elif code.startswith("minitable:"):
            labs = [x.strip() for x in code.split(":", 1)[1].split(",") if x.strip()]
            if not labs:
                fail(f"{name}: шорткод [[minitable:метка1,метка2]] — не указаны метки")
            for lab in labs:
                if lab not in article_ctx["global_products"]:
                    fail(f"{name}: шорткод [[{code}]] — товара «{lab}» нет в products ни одной статьи")
                if article_ctx["global_products"][lab].get("conflict"):
                    fail(f"{name}: шорткод [[{code}]] — метка «{lab}» встречается в статьях с разными "
                         f"данными ({article_ctx['global_products'][lab]['conflict']})")
        elif code.startswith("product:"):
            lab = code.split(":", 1)[1].strip()
            if lab not in by_label:
                fail(f"{name}: шорткод [[{code}]] — товара «{lab}» нет в products "
                     f"(доступны: {', '.join(by_label) or 'нет'})")
        else:
            fail(f"{name}: неизвестный шорткод [[{code}]]")
        shortcodes.append(code)
        return f"\nSHORTCODEX{len(shortcodes) - 1}X\n"

    body_md = SHORTCODE_RE.sub(sc_repl, body_md)

    # AFF-метки проверяем и заменяем до рендера, чтобы неизвестная метка падала сразу
    def repl(m):
        label = m.group(1)
        if label not in aff:
            fail(f"неизвестная партнёрская метка AFF:{label} — добавьте её в affiliate.json")
        used_labels.add(label)
        return f"AFFLINK{label}ENDAFF"

    body_md = re.sub(r"\(AFF:([A-Za-z0-9_\-]+)\)", lambda m: f"({repl(m)})", body_md)
    html = markdown.markdown(
        body_md, extensions=["tables", "attr_list", "toc"],
        extension_configs={"toc": {"permalink": False, "slugify": slugify_ru}})

    # ссылки на товары в тексте
    def link_repl(m):
        attrs, label, text = m.group(1), m.group(2), m.group(3)
        data = aff[label]
        url = build_aff_url(label, data)
        cls = "btn" if text.strip().startswith("Смотреть цену") else ""
        cls_attr = f' class="{cls}"' if cls else ""
        a = (f'<a{cls_attr} href="{url.replace("&", "&amp;")}" rel="{AFF_REL}" '
             f'target="_blank" data-product="{label}" data-place="text">{text}</a>')
        if data.get("ad_label"):
            a += " " + ad_mark_inline_html(data["ad_label"])
        return a

    html = re.sub(r'<a ([^>]*?)href="AFFLINK([A-Za-z0-9_\-]+)ENDAFF"[^>]*>(.*?)</a>',
                  link_repl, html, flags=re.S)
    if "AFFLINK" in html:
        fail("не все AFF-ссылки обработаны (проверьте синтаксис [текст](AFF:метка))")

    # оглавление из h2 (id уже проставлены toc/attr_list)
    toc_items = [(m.group(1), strip_tags(m.group(2)))
                 for m in re.finditer(r'<h2 id="([^"]+)"[^>]*>(.*?)</h2>', html, re.S)]

    def render_block(code):
        ctx = {"products": products, "picks": article_ctx["picks"], "toc": toc_items,
               "updated_ru": article_ctx["updated_ru"]}
        if code.startswith("photo:"):
            fname, _, cap = code.split(":", 1)[1].partition("|")
            fname, cap = fname.strip(), cap.strip()
            with Image.open(STATIC / "img" / fname) as im:
                w, h = im.size
            alt = re.sub(r"\s*\(фото автора\)\.?\s*$", "", cap).rstrip(" .") 
            return (f'<figure class="photo"><img src="/img/{fname}" alt="{html_escape(alt, quote=True)}" '
                    f'width="{w}" height="{h}" loading="lazy" decoding="async">'
                    f'<figcaption>{html_escape(cap)}</figcaption></figure>')
        if code.startswith("scheme:"):
            fname, _, cap = code.split(":", 1)[1].partition("|")
            fname, cap = fname.strip(), cap.strip()
            svg = (STATIC / "img" / fname).read_text(encoding="utf-8")
            vb = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"', svg)
            if not vb:
                fail(f"схема {fname}: нет viewBox")
            w, h = (str(int(float(x))) for x in vb.groups())
            alt = re.sub(r"\s*\(схема santehrazbor\.ru\)\.?\s*$", "", cap).rstrip(" .")
            ver = asset_hash(f"img/{fname}")
            return (f'<figure class="scheme"><a href="/img/{fname}?v={ver}" target="_blank" rel="noopener">'
                    f'<img src="/img/{fname}?v={ver}" alt="{html_escape(alt, quote=True)}" '
                    f'width="{w}" height="{h}" loading="lazy" decoding="async"></a>'
                    f'<figcaption>{html_escape(cap)}</figcaption></figure>')
        if code.startswith("minitable:"):
            # товары берём из глобального индекса: дата цены — prices_checked статьи-источника (иначе updated, иначе date)
            rows = [article_ctx["global_products"][x.strip()]
                    for x in code.split(":", 1)[1].split(",") if x.strip()]
            for r in rows:
                used_labels.add(r["p"]["label"])
            return env.get_template("blocks/minitable.html").render(rows=rows)
        if code.startswith("product:"):
            lab = code.split(":", 1)[1].strip()
            used_labels.add(lab)
            return env.get_template("blocks/product.html").render(p=by_label[lab], **ctx)
        if code in ("picks", "compare"):
            for p in (article_ctx["picks"] if code == "picks" else products):
                used_labels.add(p["label"])
        return env.get_template(f"blocks/{code}.html").render(**ctx)

    # таблицы markdown — в обёртку (до подстановки блоков, у которых своя разметка)
    html = re.sub(r"<table>", '<div class="table-wrap"><table>', html)
    html = html.replace("</table>", "</table></div>")

    html = re.sub(r"<p>SHORTCODEX(\d+)X</p>",
                  lambda m: render_block(shortcodes[int(m.group(1))]), html)
    if "SHORTCODEX" in html:
        fail(f"{name}: не все шорткоды обработаны (каждый должен стоять на отдельной строке)")

    return nbsp_text(html)


def plitka_noscript_html():
    """Таблицы готовых значений для страницы калькулятора плитки без JS (формулы — из calc_plitka_ref)."""
    g = ['<h2>Расход затирки Ceresit CE 33 Plus, кг/м²</h2>',
         '<p>Плотность 1,1 кг/дм³, запас не включён. Столбцы — толщина плитки.</p>',
         '<div class="table-wrap"><table><thead><tr><th>Плитка, см</th><th>Шов, мм</th>'
         '<th>8 мм</th><th>9 мм</th><th>10 мм</th></tr></thead><tbody>']
    for fmt_name, j, vals in plitka.grout_table_rows():
        g.append(f"<tr><td>{fmt_name}</td><td>{j}</td>" + "".join(f"<td>{plitka.fmt(v, 2)}</td>" for v in vals) + "</tr>")
    g.append("</tbody></table></div>")
    g += ['<h2>Расход плиточного клея Ceresit CM 11 Plus</h2>',
          '<div class="table-wrap"><table><thead><tr><th>Большая сторона плитки</th><th>Зуб шпателя, мм</th>'
          '<th>Расход, кг/м²</th><th>На 10 м², кг</th></tr></thead><tbody>']
    for lab, tooth, rate, per10 in plitka.glue_table_rows():
        g.append(f"<tr><td>{lab}</td><td>{tooth}</td><td>{plitka.fmt(rate, 1)}</td><td>{plitka.fmt(per10, 0)}</td></tr>")
    g.append("</tbody></table></div>")
    return "\n".join(g)


def zatirka_noscript_html():
    """Таблицы готовых значений для страницы калькулятора затирки без JS (формулы — из calc_zatirka_ref)."""
    out = []
    for title, rho_txt, rho in (("цементной затирки (плотность 1,1 кг/дм³, как у Ceresit CE 33 Plus)", "1,1", 1.1),
                                ("эпоксидной затирки (плотность 1,55 кг/дм³, как у Litokol Starlike EVO)", "1,55", 1.55)):
        out += [f"<h2>Расход {title}, кг/м²</h2>",
                "<p>Запас не включён. Толщина плитки — типовая для размера; столбцы — ширина шва.</p>",
                '<div class="table-wrap"><table><thead><tr><th>Плитка, см</th><th>Толщина, мм</th>'
                + "".join(f"<th>Шов {zatirka.fmt(j, 1)} мм</th>" for j in zatirka.TABLE_JOINTS)
                + "</tr></thead><tbody>"]
        for label, t, vals in zatirka.table_rows(rho):
            out.append(f"<tr><td>{label}</td><td>{t}</td>" + "".join(f"<td>{zatirka.fmt(v, 2)}</td>" for v in vals) + "</tr>")
        out.append("</tbody></table></div>")
    return "\n".join(out)


def vodonagrevatel_noscript_html():
    """Таблицы готовых значений для страницы калькулятора водонагревателя без JS (формулы — из calc_vodonagrevatel_ref)."""
    vn = vodonagrevatel
    out = ["<h2>Какой объём бака нужен по числу людей</h2>",
           "<p>Душ 8 минут на человека, 7,2 л/мин, смесь 40 °C, бак 60 °C, холодная вода 5 °C, ТЭН 2 кВт, перерыв между душами 0, догрев за время мытья учтён. «Нужно» — из бака, л.</p>",
           '<div class="table-wrap"><table><thead><tr><th>Человек подряд</th><th>Нужно из бака, л</th><th>Бак без ванны, л</th>'
           "<th>Нужно с ванной 150 л, л</th><th>Бак с ванной, л</th></tr></thead><tbody>"]
    for n, need_a, rec_a, need_b, rec_b in vn.people_table():
        out.append(f"<tr><td>{n}</td><td>{vn.fmt(need_a)}</td><td>{rec_a if rec_a else 'больше 200'}</td>"
                   f"<td>{vn.fmt(need_b)}</td><td>{rec_b if rec_b else 'больше 200'}</td></tr>")
    out.append("</tbody></table></div>")
    out += ["<h2>Сколько греется бак от 5 до 60 °C</h2>",
            "<p>Без учёта теплопотерь, по формуле 1,163 × V × ΔT / P; по паспорту обычно чуть дольше.</p>",
            '<div class="table-wrap"><table><thead><tr><th>Объём, л</th>'
            + "".join(f"<th>{vn.fmt(p, 1)} кВт</th>" for p in vn.TABLE_HEAT_POWERS) + "</tr></thead><tbody>"]
    for v, mins in vn.heat_table():
        out.append(f"<tr><td>{v}</td>" + "".join(f"<td>{vn.fmt_hm(m)}</td>" for m in mins) + "</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


# калькулятор (slug) -> функция, строящая таблицы для <noscript>
NOSCRIPT_BUILDERS = {"kalkulyator-plitki": plitka_noscript_html, "kalkulyator-zatirki": zatirka_noscript_html,
                     "kalkulyator-vodonagrevatelya": vodonagrevatel_noscript_html}


def md_plain_text(body_md):
    """Markdown-тело -> чистый текст для поискового индекса: без шорткодов, ссылок, разметки и таблиц-разделителей."""
    t = SHORTCODE_RE.sub(" ", body_md)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)           # картинки
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)        # ссылки -> текст
    t = re.sub(r"^\s*\|?[\s:|-]{3,}\|?\s*$", " ", t, flags=re.M)  # разделитель таблицы
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"^\s*(#{1,6}|>|[-*+]|\d+\.)\s+", "", t, flags=re.M)
    t = re.sub(r"[*_`|]+", " ", t)
    # вычищаем эмодзи и пиктограммы (U+2600–27BF, U+1F000+, U+FE0F, приватная зона)
    t = re.sub("[☀-➿🀀-🿿️-]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    # пробелы, оставшиеся от снятых тегов, перед знаками препинания и после «(»
    t = re.sub(r"\s+([,.:;)!?])", r"\1", t)
    return re.sub(r"\(\s+", "(", t)


def md_headings(body_md):
    """Заголовки h2/h3 markdown-тела (текстом)."""
    out = []
    for m in re.finditer(r"^#{2,3}\s+(.+?)\s*$", SHORTCODE_RE.sub("", body_md), re.M):
        out.append(re.sub(r"[*_`]+", "", re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", m.group(1))).strip())
    return out


SEARCH_TEXT_LIMIT = 3000  # символов текста на запись: индекс остаётся компактным


def main():
    config = load_json("config.json")
    aff = load_json("affiliate.json")
    base = config["base_url"].rstrip("/")

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    env.globals["style_ver"] = asset_hash("style.css")
    env.filters.update(rub=rub, num=fmt_int, plural=plural, count_word=count_word,
                       md=md_inline, nbsp=lambda s: nbsp_text(str(s)))

    # --- глобальный индекс товаров всех статей (для [[minitable:...]]): метка -> {p, updated_ru}; updated_ru = prices_checked → updated → date
    global_products = {}
    for path in sorted(CONTENT.glob("*.md")):
        meta, _ = split_front_matter(path.read_text(encoding="utf-8"), path)
        if "date" not in meta:
            continue  # ошибку про отсутствие поля выдаст основной цикл
        upd_ru = ru_date(to_date(meta.get("prices_checked") or meta.get("updated") or meta["date"]))
        for p in build_products(meta, aff, path.name)[0]:
            # конфликт (одна метка с разными данными в двух статьях) — ошибка только при использовании в minitable
            prev = global_products.get(p["label"])
            # сравниваем только поля, которые выводит minitable (subtitle, отзывы и т. п. могут различаться)
            fields = ("name", "material", "price", "status", "href", "ad_label")
            if prev and not prev.get("conflict") and                     [prev["p"].get(k) for k in fields] != [p.get(k) for k in fields]:
                prev["conflict"] = f"{prev['src']} и {path.name}"
            global_products.setdefault(p["label"], {"p": p, "updated_ru": upd_ru, "src": path.name})

    # --- читаем статьи
    articles = []
    used_labels = set()
    for path in sorted(CONTENT.glob("*.md")):
        meta, body = split_front_matter(path.read_text(encoding="utf-8"), path)
        body = apply_prices_date(body, meta, path.name)
        for key in ("title", "description", "slug", "date"):
            if key not in meta:
                fail(f"{path.name}: в front matter нет поля {key}")
        published = to_date(meta["date"])
        updated = to_date(meta.get("updated", meta["date"]))
        # H1 выводим шаблоном — убираем из тела
        h1 = re.match(r"\s*#\s+(.+?)\s*\n", body)
        h1_text = h1.group(1) if h1 else meta["title"]
        if h1:
            body = body[h1.end():]
        faq = parse_faq(body)
        cover = meta.get("cover")
        if cover:
            if not (STATIC / "img" / cover).is_file():
                fail(f"{path.name}: cover static/img/{cover} не найден")
            if not meta.get("cover_alt"):
                fail(f"{path.name}: у cover нет cover_alt")
            cover_w, cover_h = cover_size(cover)
        products, picks = build_products(meta, aff, path.name)
        html = render_markdown(body, aff, used_labels, env, {
            "name": path.name, "products": products, "picks": picks,
            "global_products": global_products, "updated_ru": ru_date(updated)})
        articles.append({
            "title": meta["title"], "h1": h1_text, "description": meta["description"],
            "seo_title": meta.get("seo_title") or meta["title"],
            "seo_description": meta.get("seo_description") or meta["description"],
            "category": meta.get("category"),
            "cover": cover, "cover_alt": meta.get("cover_alt"),
            "cover_w": cover_w if cover else None, "cover_h": cover_h if cover else None,
            "slug": meta["slug"], "published": published, "updated": updated,
            "published_ru": ru_date(published), "updated_ru": ru_date(updated),
            "body": html, "body_md": body, "faq": faq, "path": f"/{meta['slug']}/",
            "products": products, "picks": picks,
        })
    articles.sort(key=lambda a: a["updated"], reverse=True)

    # --- калькуляторы: content/calc/NN-slug.md (type: calculator); тело — те же шорткоды, что у статей
    calcs = []
    for path in sorted((CONTENT / "calc").glob("*.md")):
        meta, body = split_front_matter(path.read_text(encoding="utf-8"), path)
        body = apply_prices_date(body, meta, path.name)
        for key in ("title", "description", "slug", "script", "type"):
            if key not in meta:
                fail(f"calc/{path.name}: в front matter нет поля {key}")
        if meta["type"] != "calculator":
            fail(f"calc/{path.name}: type должен быть calculator")
        if not (STATIC / "js" / meta["script"]).is_file():
            fail(f"calc/{path.name}: скрипт static/js/{meta['script']} не найден")
        if not (TEMPLATES / "calc" / f"{meta['slug']}.html").is_file():
            fail(f"calc/{path.name}: нет шаблона формы templates/calc/{meta['slug']}.html")
        published = to_date(meta.get("published", meta.get("date")))
        updated = to_date(meta.get("updated", published))
        h1 = re.match(r"\s*#\s+(.+?)\s*\n", body)
        if h1:
            body = body[h1.end():]
        # товары блока «Затирка под ваш расчёт»: products в front matter, как у статей
        calc_prods, _ = build_products(meta, aff, f"calc/{path.name}")
        for cp in calc_prods:
            used_labels.add(cp["label"])
        html = render_markdown(body, aff, used_labels, env, {
            "name": path.name, "products": [], "picks": [],
            "global_products": global_products, "updated_ru": ru_date(updated)})
        builder = NOSCRIPT_BUILDERS.get(meta["slug"])
        calcs.append({
            "title": meta["title"], "h1": meta.get("h1") or (h1.group(1) if h1 else meta["title"]),
            "description": meta["description"], "lead": meta.get("lead", ""),
            "seo_title": meta.get("seo_title") or meta["title"],
            "seo_description": meta.get("seo_description") or meta["description"],
            "slug": meta["slug"], "script": meta["script"],
            "products": {cp["label"]: cp for cp in calc_prods},
            "published": published, "updated": updated, "updated_ru": ru_date(updated),
            "body": html, "body_md": body, "faq": parse_faq(body), "path": f"/{meta['slug']}/",
            "noscript": builder() if builder else "",
        })

    # --- чистим docs/
    # Чистим содержимое, а не саму папку: её может держать открытой оболочка (Windows)
    DOCS.mkdir(exist_ok=True)
    for child in DOCS.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    site = {**config, "year": date.today().year}

    def write(rel, html):
        p = DOCS / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")

    def render(template, path, **ctx):
        ctx.setdefault("canonical", base + path)
        ctx.setdefault("og_type", "website")
        # og-картинка: static/img/og/<slug>.png, иначе общая default.png
        og_name = path.strip("/")
        if not og_name or not (STATIC / "img" / "og" / f"{og_name}.png").exists():
            og_name = "default"
        ctx.setdefault("og_image", f"{base}/img/og/{og_name}.png")
        return env.get_template(template).render(site=site, path=path, **ctx)

    def og_image_url(path):
        name = path.strip("/")
        if not (STATIC / "img" / "og" / f"{name}.png").exists():
            name = "default"
        return f"{base}/img/og/{name}.png"

    pages = []  # (path, lastmod)

    # --- разделы (хабы): только те, где есть хотя бы одна статья
    categories = config.get("categories", {})
    for a in articles:
        if a["category"] and a["category"] not in categories:
            fail(f"статья {a['slug']}: категория {a['category']} не описана в config.json")
        a["cat"] = None
        if a["category"]:
            a["cat"] = {**categories[a["category"]], "slug": a["category"],
                        "path": f"/{a['category']}/"}
    hubs = []
    for slug, cat in categories.items():
        arts = [a for a in articles if a["category"] == slug]
        if arts:
            hubs.append({**cat, "slug": slug, "path": f"/{slug}/", "articles": arts,
                         "updated": max(a["updated"] for a in arts)})
    nav_urls = {i["url"] for i in config["nav"]}

    def nav_active(path, article=None):
        # Своё меню важнее: статья «Материалы» подсвечивает себя, а не раздел
        if path in nav_urls:
            return path
        if article and article["cat"]:
            return article["cat"]["path"]
        return None

    write("index.html", render(
        "index.html", "/", title=config["home_title"],
        description=config["home_description"], nav_active="/",
        articles=articles, hubs=hubs, calcs=calcs))
    pages.append(("/", max(a["updated"] for a in articles) if articles else date.today()))

    for a in articles:
        jsonld = [
            {
                "@context": "https://schema.org", "@type": "Article",
                "headline": a["h1"], "description": a["description"],
                "datePublished": iso_dt(a["published"]),
                "dateModified": iso_dt(a["updated"]),
                "inLanguage": "ru",
                "mainEntityOfPage": base + a["path"],
                "author": {"@type": "Person", "name": "Николай", "url": base + "/o-proekte/"},
                "image": og_image_url(a["path"]),
                "publisher": {"@type": "Organization", "name": config["site_name"],
                              "logo": {"@type": "ImageObject", "url": base + "/apple-touch-icon.png"}},
            },
            {
                "@context": "https://schema.org", "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Главная", "item": base + "/"},
                ] + ([{"@type": "ListItem", "position": 2, "name": a["cat"]["name"],
                       "item": base + a["cat"]["path"]}] if a["cat"] else []) + [
                    {"@type": "ListItem", "position": 3 if a["cat"] else 2, "name": a["h1"],
                     "item": base + a["path"]},
                ],
            },
        ]
        if a["products"]:
            jsonld.append({
                "@context": "https://schema.org", "@type": "ItemList",
                "name": f"Модели в статье: {a['h1']}",
                # товары без наличия (status: unavailable) в разметку не попадают
                "itemListElement": [
                    {"@type": "ListItem", "position": i, "name": p["name"],
                     "url": p["market_url"]}
                    for i, p in enumerate(
                        [p for p in a["products"] if p.get("status") != "unavailable"], 1)
                ],
            })
        if a["faq"]:
            jsonld.append({
                "@context": "https://schema.org", "@type": "FAQPage",
                "mainEntity": [
                    {"@type": "Question", "name": f["q"],
                     "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                    for f in a["faq"]
                ],
            })
        jsonld_str = [json.dumps(j, ensure_ascii=False).replace("</", "<\\/") for j in jsonld]
        write(f"{a['slug']}/index.html", render(
            "article.html", a["path"], title=a["seo_title"], description=a["seo_description"],
            nav_active=nav_active(a["path"], a), article=a, jsonld=jsonld_str, og_type="article",
            related=[x for x in articles if x is not a]))
        pages.append((a["path"], a["updated"]))

    for c in calcs:
        jsonld = [
            {
                "@context": "https://schema.org", "@type": "WebApplication",
                "name": c["h1"], "description": c["description"], "url": base + c["path"],
                "applicationCategory": "UtilitiesApplication", "operatingSystem": "Any",
                "browserRequirements": "Requires JavaScript", "inLanguage": "ru",
                "image": og_image_url(c["path"]),
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "RUB"},
                "dateModified": iso_dt(c["updated"]),
                "author": {"@type": "Person", "name": "Николай", "url": base + "/o-proekte/"},
            },
            {
                "@context": "https://schema.org", "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Главная", "item": base + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Калькуляторы", "item": base + "/kalkulyatory/"},
                    {"@type": "ListItem", "position": 3, "name": c["h1"], "item": base + c["path"]},
                ],
            },
        ]
        if c["faq"]:
            jsonld.append({
                "@context": "https://schema.org", "@type": "FAQPage",
                "mainEntity": [
                    {"@type": "Question", "name": f["q"],
                     "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                    for f in c["faq"]
                ],
            })
        jsonld_str = [json.dumps(j, ensure_ascii=False).replace("</", "<\\/") for j in jsonld]
        write(f"{c['slug']}/index.html", render(
            "calculator.html", c["path"], title=c["seo_title"], description=c["seo_description"],
            nav_active="/kalkulyatory/", article=c, jsonld=jsonld_str, script_ver=asset_hash(f"js/{c['script']}")))
        pages.append((c["path"], c["updated"]))
    if calcs:
        write("kalkulyatory/index.html", render(
            "calc_hub.html", "/kalkulyatory/", title="Калькуляторы для ремонта ванной — Сантехразбор",
            description="Онлайн-калькуляторы: сколько нужно плитки, клея и затирки. Считают сразу при вводе, формулы и источники показаны.",
            nav_active="/kalkulyatory/", calcs=calcs))
        pages.append(("/kalkulyatory/", max(c["updated"] for c in calcs)))

    for h in hubs:
        write(f"{h['slug']}/index.html", render(
            "category.html", h["path"], title=h["seo_title"], description=h["seo_description"],
            nav_active=h["path"], hub=h))
        pages.append((h["path"], h["updated"]))

    write("o-proekte/index.html", render(
        "about.html", "/o-proekte/", nav_active="/o-proekte/", title="О проекте: кто пишет и как отбираем модели — Сантехразбор",
        description="Кто мы, как отбираем модели и почему на сайте есть партнёрские ссылки."))
    write("privacy/index.html", render(
        "privacy.html", "/privacy/", title=f"Политика конфиденциальности — {config['site_name']}",
        description="Какие данные собирает сайт: Яндекс Метрика, GoatCounter и cookie для статистики."))
    today = date.today()
    pages.append(("/o-proekte/", today))
    pages.append(("/privacy/", today))

    # --- поиск: страница /poisk/ (noindex, вне sitemap) и клиентский индекс
    search_index = []
    for a in articles:
        search_index.append({
            "url": a["path"], "title": a["h1"], "description": md_plain_text(a["description"]),
            "section": a["cat"]["name"] if a["cat"] else "Статья",
            "headings": md_headings(a["body_md"]),
            "products": [p["name"] for p in a["products"]],
            "text": md_plain_text(a["body_md"])[:SEARCH_TEXT_LIMIT]})
    for c in calcs:
        search_index.append({
            "url": c["path"], "title": c["h1"], "description": md_plain_text(c["description"]),
            "section": "Калькулятор", "headings": md_headings(c["body_md"]),
            "products": [p["name"] for p in c["products"].values()],
            "text": md_plain_text(c["body_md"])[:SEARCH_TEXT_LIMIT]})
    for h in hubs:
        search_index.append({
            "url": h["path"], "title": h["name"], "description": h["seo_description"],
            "section": "Раздел", "headings": [], "products": [],
            "text": " ".join(x["title"] for x in h["articles"])})
    search_json = json.dumps(search_index, ensure_ascii=False, separators=(",", ":"))
    write("search-index.json", search_json)
    write("poisk/index.html", render(
        "search.html", "/poisk/", title=f"Поиск по сайту — {config['site_name']}",
        description="Поиск по статьям и калькуляторам сайта.", nav_active=None, noindex="follow", hubs=hubs,
        articles=articles, calcs=calcs, search_ver=asset_hash("js/search.js"),
        index_ver=hashlib.md5(search_json.encode("utf-8")).hexdigest()[:8]))
    print(f"Поисковый индекс: {len(search_index)} записей, {len(search_json.encode('utf-8')) // 1024} КБ")

    write("404.html", render(
        "404.html", "/404.html", title=f"Страница не найдена — {config['site_name']}",
        description="Такой страницы нет.", noindex=True))

    # --- служебные файлы
    urls = "\n".join(
        f"    <url>\n        <loc>{base}{p}</loc>\n        <lastmod>{d.isoformat()}</lastmod>\n    </url>"
        for p, d in pages)
    write("sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "\n</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n")
    # llms.txt (llmstxt.org): краткая карта сайта для языковых моделей; в sitemap не входит
    llms = [
        f"# {config['site_name']}",
        "",
        f"> {config['home_description']}",
        "",
        "Сайт о выборе сантехники: смесители, гигиенические души, душевые системы. В статьях разбираем, "
        "что внутри: материал корпуса, картридж, гарантия, реальные отзывы покупателей. "
        "Автор — Николай. Модели для подборок отбираем по характеристикам из карточек и отзывам покупателей.",
        "",
        "## Разделы",
        "",
    ]
    llms += [f"- [{h['name']}]({base}{h['path']}): {h['seo_description']}" for h in hubs]
    llms += ["", "## Статьи", ""]
    llms += [f"- [{a['title']}]({base}{a['path']}): {a['description']}" for a in articles]
    if calcs:
        llms += ["", "## Калькуляторы", ""]
        llms += [f"- [{c['h1']}]({base}{c['path']}): {c['description']}" for c in calcs]
    llms += ["", "## О проекте", "",
             f"- [О проекте]({base}/o-proekte/): кто мы и как отбираем модели."]
    write("llms.txt", "\n".join(llms) + "\n")
    write("CNAME", "santehrazbor.ru\n")
    write(".nojekyll", "")
    shutil.copytree(STATIC, DOCS, dirs_exist_ok=True)

    unused = set(aff) - used_labels
    print(f"Готово: {len(articles)} статей, {len(calcs)} калькуляторов, {len(pages) + 1} страниц, "
          f"использовано меток: {len(used_labels)}")
    if unused:
        print("Неиспользованные метки:", ", ".join(sorted(unused)))


if __name__ == "__main__":
    main()
