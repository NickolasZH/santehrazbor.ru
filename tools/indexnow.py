"""Отправка изменённых URL в IndexNow (Яндекс, Bing и др.).

Запуск из site/: PYTHONIOENCODING=utf-8 python tools/indexnow.py [--all] [--dry-run]
Берёт URL и lastmod из docs/sitemap.xml, ключ — из config.json (indexnow_key).
Состояние (что уже отправлено) — data/indexnow_last.json.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = ROOT / "docs" / "sitemap.xml"
CONFIG = ROOT / "config.json"
STATE = ROOT / "data" / "indexnow_last.json"
ENDPOINTS = ["https://yandex.com/indexnow", "https://api.indexnow.org/indexnow"]
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def read_sitemap():
    tree = ET.parse(SITEMAP)
    result = {}
    for u in tree.getroot().findall("s:url", NS):
        loc = u.findtext("s:loc", default="", namespaces=NS).strip()
        lastmod = u.findtext("s:lastmod", default="", namespaces=NS).strip()
        if loc:
            result[loc] = lastmod
    return result


def post(endpoint, payload):
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="отправить все URL, не только изменённые")
    ap.add_argument("--dry-run", action="store_true", help="только показать список, без сети и записи состояния")
    args = ap.parse_args()

    key = json.loads(CONFIG.read_text(encoding="utf-8")).get("indexnow_key")
    if not key:
        print("В config.json нет indexnow_key")
        return 1
    sitemap = read_sitemap()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    urls = [u for u, d in sitemap.items() if args.all or state.get(u) != d]

    if not urls:
        print("нечего отправлять")
        return 0
    print(f"URL к отправке: {len(urls)}")
    for u in urls:
        print("  " + u)
    if args.dry_run:
        return 0

    payload = {"host": "santehrazbor.ru", "key": key,
               "keyLocation": f"https://santehrazbor.ru/{key}.txt", "urlList": urls}
    ok = False
    failed = False
    for ep in ENDPOINTS:
        try:
            code = post(ep, payload)
        except (urllib.error.URLError, OSError) as e:
            print(f"{ep}: ошибка сети: {e}")
            failed = True
            continue
        print(f"{ep}: {code}")
        if code in (200, 202):
            ok = True
    if ok:
        state.update({u: sitemap[u] for u in urls})
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
