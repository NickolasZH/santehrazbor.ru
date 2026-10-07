#!/usr/bin/env python3
"""Статический генератор сайта: content/*.md -> docs/ (GitHub Pages).

Запуск: python build.py
"""
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def render_markdown(body_md, aff, used_labels):
    # AFF-метки проверяем и заменяем до рендера, чтобы неизвестная метка падала сразу
    def repl(m):
        label = m.group(1)
        if label not in aff:
            fail(f"неизвестная партнёрская метка AFF:{label} — добавьте её в affiliate.json")
        used_labels.add(label)
        return f"AFFLINK{label}ENDAFF"

    body_md = re.sub(r"\(AFF:([A-Za-z0-9_\-]+)\)", lambda m: f"({repl(m)})", body_md)
    html = markdown.markdown(body_md, extensions=["tables", "attr_list", "toc"],
                             extension_configs={"toc": {"permalink": False}})

    # ссылки на товары
    def link_repl(m):
        attrs, label, text = m.group(1), m.group(2), m.group(3)
        data = aff[label]
        url = build_aff_url(label, data)
        cls = "btn" if text.strip().startswith("Смотреть цену") else ""
        cls_attr = f' class="{cls}"' if cls else ""
        a = (f'<a{cls_attr} href="{url.replace("&", "&amp;")}" rel="{AFF_REL}" '
             f'target="_blank">{text}</a>')
        if data.get("ad_label"):
            a += f' <span class="ad-mark">{data["ad_label"]}</span>'
        return a

    html = re.sub(r'<a ([^>]*?)href="AFFLINK([A-Za-z0-9_\-]+)ENDAFF"[^>]*>(.*?)</a>',
                  link_repl, html, flags=re.S)
    if "AFFLINK" in html:
        fail("не все AFF-ссылки обработаны (проверьте синтаксис [текст](AFF:метка))")

    # таблицы в обёртку
    html = re.sub(r"<table>", '<div class="table-wrap"><table>', html)
    html = html.replace("</table>", "</table></div>")
    return html


def main():
    config = load_json("config.json")
    aff = load_json("affiliate.json")
    base = config["base_url"].rstrip("/")

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))

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
        html = render_markdown(body, aff, used_labels)
        articles.append({
            "title": meta["title"], "h1": h1_text, "description": meta["description"],
            "slug": meta["slug"], "published": published, "updated": updated,
            "published_ru": ru_date(published), "updated_ru": ru_date(updated),
            "body": html, "faq": faq, "path": f"/{meta['slug']}/",
        })
    articles.sort(key=lambda a: a["updated"], reverse=True)

    # --- чистим docs/
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir()

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

    write("index.html", render(
        "index.html", "/", title=f"{config['site_name']} — {config['tagline']}",
        description=config["tagline"] + ". Разбираем, что внутри: материалы, картриджи, "
                    "подключение — и только потом выбираем модели.",
        articles=articles))
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
                    {"@type": "ListItem", "position": 2, "name": a["h1"], "item": base + a["path"]},
                ],
            },
        ]
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
            "article.html", a["path"], title=a["title"], description=a["description"],
            article=a, jsonld=jsonld_str, og_type="article"))
        pages.append((a["path"], a["updated"]))

    write("o-proekte/index.html", render(
        "about.html", "/o-proekte/", title=f"О проекте — {config['site_name']}",
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
