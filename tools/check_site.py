#!/usr/bin/env python3
"""Проверка собранного сайта в docs/ (только отчёт, ничего не правит).

Локально: внутренние ссылки и якоря, остатки шорткодов, svg/png, sitemap.xml, erid у партнёрских ссылок.
С флагом --live дополнительно запрашивает страницы из sitemap на https://santehrazbor.ru (нужна сеть).
Печатает markdown-раздел «Проверка сайта»; с --out FILE дописывает его в файл.
Правила — в tools/README.md. Только стандартная библиотека.
"""
import argparse
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE_HOST = "santehrazbor.ru"
AFF_HOSTS = ("market.yandex.ru", "ya.cc")
SKIP_PAGES = {"404.html"}  # служебные страницы, в sitemap не нужны
UA = "Mozilla/5.0 (compatible; santehrazbor-site-check)"


class Page(HTMLParser):
    """Собирает ссылки, id, видимый текст и признаки страницы."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []      # (тег, атрибут, значение, rel)
        self.ids = set()
        self.text = []
        self.noindex = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        for k in ("id", "name"):
            if a.get(k):
                self.ids.add(a[k])
        if tag == "meta" and (a.get("name") or "").lower() == "robots" and "noindex" in (a.get("content") or ""):
            self.noindex = True
        if tag == "link" and a.get("rel") in ("canonical", "alternate"):
            return  # canonical указывает на боевой домен — проверяется в --live через sitemap
        for k in ("href", "src"):
            if a.get(k) is not None:
                self.links.append((tag, k, a[k], a.get("rel") or ""))
        if a.get("srcset"):
            for part in a["srcset"].split(","):
                if part.strip():
                    self.links.append((tag, "srcset", part.strip().split()[0], ""))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def page_url_path(f):
    """docs/a/b/index.html -> /a/b/ ; docs/x.html -> /x.html."""
    rel = f.relative_to(DOCS).as_posix()
    return "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)


def resolve_target(url_path):
    """URL-путь -> файл в docs/ или None."""
    p = unquote(url_path).lstrip("/")
    cand = DOCS / p
    if url_path.endswith("/") or not p:
        cand = cand / "index.html"
    if cand.is_file():
        return cand
    if cand.is_dir() and (cand / "index.html").is_file():
        return cand / "index.html"
    return None


def parse_page(f):
    pg = Page()
    pg.feed(f.read_text(encoding="utf-8"))
    return pg


def check_local():
    issues = []  # (раздел, страница, описание)
    files = sorted(DOCS.rglob("*.html"))
    pages = {f: parse_page(f) for f in files}
    ids_cache = {f: pg.ids for f, pg in pages.items()}
    svgs = set()

    for f, pg in pages.items():
        here = page_url_path(f)
        rel = f.relative_to(DOCS).as_posix()
        raw_text = "".join(pg.text)
        for token in ("[[", "]]", "AFF:"):
            if token in raw_text:
                i = raw_text.index(token)
                issues.append(("Остатки шорткодов", rel, f"«{token}» в тексте: …{raw_text[max(0, i - 30):i + 40].strip()}…"))
        has_aff, has_mark = False, "Реклама" in raw_text
        for tag, attr, val, relattr in pg.links:
            val = val.strip()
            if not val or val.startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            u = urlsplit(val)
            host = u.netloc.lower()
            if host in AFF_HOSTS or (host.endswith("market.yandex.ru")):
                has_aff = True
                if not any(k == "erid" and v for k, v in parse_qsl(u.query)):
                    issues.append(("Партнёрские ссылки без erid", rel, val[:100]))
                continue
            if host and host != SITE_HOST and host != "www." + SITE_HOST:
                continue  # внешние домены не проверяем
            path = u.path
            if not host and not path:       # только #якорь на этой же странице
                target = f
            else:
                if not path.startswith("/"):
                    base = here if here.endswith("/") else here.rsplit("/", 1)[0] + "/"
                    path = base + path
                target = resolve_target(path)
            if target is None:
                issues.append(("Битые внутренние ссылки", rel, f"{attr}={val[:100]}"))
                continue
            if target.suffix == ".svg":
                svgs.add(target)
            if u.fragment and target.suffix == ".html":
                if target not in ids_cache:
                    ids_cache[target] = parse_page(target).ids
                if unquote(u.fragment) not in ids_cache[target]:
                    issues.append(("Битые якоря", rel, f"{val[:100]} — id не найден на {target.relative_to(DOCS).as_posix()}"))
        if has_aff and not has_mark:
            issues.append(("Партнёрские ссылки без метки «Реклама»", rel, "на странице нет текста «Реклама»"))

    # все svg из docs/ должны быть валидным XML
    for s in sorted(set(DOCS.rglob("*.svg")) | svgs):
        try:
            ET.parse(s)
        except ET.ParseError as e:
            issues.append(("Невалидные svg", s.relative_to(DOCS).as_posix(), str(e)))

    # sitemap
    sm = DOCS / "sitemap.xml"
    in_sitemap = set()
    if not sm.is_file():
        issues.append(("sitemap.xml", "sitemap.xml", "файла нет"))
    else:
        try:
            ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in ET.parse(sm).getroot().findall("s:url/s:loc", ns):
                u = urlsplit((loc.text or "").strip())
                if u.netloc != SITE_HOST:
                    issues.append(("sitemap.xml", "sitemap.xml", f"чужой домен: {loc.text}"))
                    continue
                t = resolve_target(u.path)
                if t is None:
                    issues.append(("sitemap.xml", "sitemap.xml", f"URL без файла в docs/: {loc.text}"))
                else:
                    in_sitemap.add(t)
        except ET.ParseError as e:
            issues.append(("sitemap.xml", "sitemap.xml", f"не парсится: {e}"))
        for f, pg in pages.items():
            name = f.relative_to(DOCS).as_posix()
            if name in SKIP_PAGES or pg.noindex or f not in in_sitemap and re.match(r"yandex_|google", f.name):
                continue
            if f not in in_sitemap:
                issues.append(("sitemap.xml", name, "страницы нет в sitemap"))
    return issues, len(files), sorted(in_sitemap)


def check_live(sitemap_files):
    issues = []
    for f in sitemap_files:
        url = f"https://{SITE_HOST}{page_url_path(f)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:  # сеть недоступна и т. п.
            issues.append(("Онлайн-проверка", url, f"{type(e).__name__}: {e}"))
            continue
        if code != 200:
            issues.append(("Онлайн-проверка", url, f"HTTP {code}"))
    return issues


def build_report(live=False):
    """-> (markdown, число_находок)."""
    issues, n_pages, in_sitemap = check_local()
    if live:
        issues += check_live(in_sitemap)
    md = ["## Проверка сайта", ""]
    mode = "локально + онлайн" if live else "локально"
    if not issues:
        md.append(f"Нарушений нет (страниц: {n_pages}, режим: {mode}).")
    else:
        md.append(f"Находок: {len(issues)} (страниц: {n_pages}, режим: {mode}). Скрипт ничего не правит.")
        groups = {}
        for sec, where, desc in issues:
            groups.setdefault(sec, []).append((where, desc))
        for sec, items in groups.items():
            md += ["", f"### {sec} ({len(items)})", "", "| Где | Что |", "|---|---|"]
            for where, desc in items[:40]:
                md.append(f"| {where.replace('|', '\\|')} | {desc.replace('|', '\\|').replace(chr(10), ' ')} |")
            if len(items) > 40:
                md.append(f"| … | ещё {len(items) - 40} |")
    return "\n".join(md) + "\n", len(issues)


def main():
    ap = argparse.ArgumentParser(description="Проверка собранного сайта в docs/ (только отчёт)")
    ap.add_argument("--live", action="store_true", help="проверить страницы из sitemap на боевом домене")
    ap.add_argument("--out", help="дописать отчёт в файл")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    md, n = build_report(args.live)
    print(md)
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            f.write("\n" + md)
    print(f"Находок: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
