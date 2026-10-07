#!/usr/bin/env python3
"""Статический генератор сайта: content/*.md -> docs/ (GitHub Pages).

Запуск: python build.py
"""
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

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
DOCS = ROOT / "docs"

AFF_REL = "sponsored nofollow noopener"


def fail(msg):
    sys.exit(f"ОШИБКА СБОРКИ: {msg}")


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


def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


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
            "ad_label": data.get("ad_label") or "", "market_url": data.get("url") or "",
            "badge_class": badge_class(p.get("badge")),
        })
    picks = meta.get("picks") or []
    by_label = {p["label"]: p for p in products}
    for lab in picks:
        if lab not in by_label:
            fail(f"{ctx_name}: в picks указана неизвестная метка «{lab}» (нет в products)")
    return products, [by_label[lab] for lab in picks]


def render_markdown(body_md, aff, used_labels, env, article_ctx):
    """markdown -> HTML со шорткодами [[picks]], [[compare]], [[product:метка]], [[toc]]."""
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
            a += f' <span class="ad-mark">{data["ad_label"]}</span>'
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


def main():
    config = load_json("config.json")
    aff = load_json("affiliate.json")
    base = config["base_url"].rstrip("/")

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    env.filters.update(rub=rub, num=fmt_int, plural=plural, count_word=count_word,
                       md=md_inline, nbsp=lambda s: nbsp_text(str(s)))

    # --- читаем статьи
    articles = []
    used_labels = set()
    for path in sorted(CONTENT.glob("*.md")):
        meta, body = split_front_matter(path.read_text(encoding="utf-8"), path)
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
        products, picks = build_products(meta, aff, path.name)
        html = render_markdown(body, aff, used_labels, env, {
            "name": path.name, "products": products, "picks": picks,
            "updated_ru": ru_date(updated)})
        articles.append({
            "title": meta["title"], "h1": h1_text, "description": meta["description"],
            "seo_title": meta.get("seo_title") or meta["title"],
            "seo_description": meta.get("seo_description") or meta["description"],
            "category": meta.get("category"),
            "slug": meta["slug"], "published": published, "updated": updated,
            "published_ru": ru_date(published), "updated_ru": ru_date(updated),
            "body": html, "faq": faq, "path": f"/{meta['slug']}/",
            "products": products, "picks": picks,
        })
    articles.sort(key=lambda a: a["updated"], reverse=True)

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
        return env.get_template(template).render(site=site, path=path, **ctx)

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
        articles=articles, hubs=hubs))
    pages.append(("/", max(a["updated"] for a in articles) if articles else date.today()))

    for a in articles:
        jsonld = [
            {
                "@context": "https://schema.org", "@type": "Article",
                "headline": a["h1"], "description": a["description"],
                "datePublished": a["published"].isoformat(),
                "dateModified": a["updated"].isoformat(),
                "inLanguage": "ru",
                "mainEntityOfPage": base + a["path"],
                "author": {"@type": "Organization", "name": config["site_name"]},
                "publisher": {"@type": "Organization", "name": config["site_name"]},
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

    for h in hubs:
        write(f"{h['slug']}/index.html", render(
            "category.html", h["path"], title=h["seo_title"], description=h["seo_description"],
            nav_active=h["path"], hub=h))
        pages.append((h["path"], h["updated"]))

    write("o-proekte/index.html", render(
        "about.html", "/o-proekte/", nav_active="/o-proekte/", title=f"О проекте — {config['site_name']}",
        description="Кто мы, как отбираем модели и почему на сайте есть партнёрские ссылки."))
    write("privacy/index.html", render(
        "privacy.html", "/privacy/", title=f"Политика конфиденциальности — {config['site_name']}",
        description="Какие данные собирает сайт: Яндекс Метрика и cookie для статистики."))
    today = date.today()
    pages.append(("/o-proekte/", today))
    pages.append(("/privacy/", today))

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
    write("CNAME", "santehrazbor.ru\n")
    write(".nojekyll", "")
    shutil.copytree(STATIC, DOCS, dirs_exist_ok=True)

    unused = set(aff) - used_labels
    print(f"Готово: {len(articles)} статей, {len(pages) + 1} страниц, "
          f"использовано меток: {len(used_labels)}")
    if unused:
        print("Неиспользованные метки:", ", ".join(sorted(unused)))


if __name__ == "__main__":
    main()
