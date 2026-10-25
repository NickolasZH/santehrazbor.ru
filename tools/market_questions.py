"""Новые вопросы покупателей и ответы продавцов с карточек Яндекс Маркета для товаров статей.

Запуск из site/: PYTHONIOENCODING=utf-8 python tools/market_questions.py [--init] [--dry-run]
Товары берутся из шорткодов [[product:id]] в content/*.md, id карточки — из affiliate.json.
Состояние ({товар: {id вопроса: число ответов}}) — data/market_questions_seen.json,
отчёт — data/reports/questions-<дата>.md. Капчу не обходит: останавливается, код выхода 2.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
AFFILIATE = ROOT / "affiliate.json"
STATE = ROOT / "data" / "market_questions_seen.json"
REPORTS = ROOT / "data" / "reports"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
PAUSE = 1.5          # секунд между запросами
MIN_HTML = 50000     # короче — считаем капчей/блокировкой
TEXT_LEN = 400       # длина вопроса и ответа в отчёте

# Вопрос встречается в JSON страницы в двух форматах: "<qid>":{"id":... и "questions":[{"id":...
QRE = re.compile(r'(?:"(\d+)":)?\{"id":(\d+),"text":"((?:[^"\\]|\\.)*)","crTimeMs":(\d+),"answerCount":(\d+)')
# ответ — элемент items с полем crTimeMs сразу за текстом (метки вроде «Ответ продавца» не подходят)
TRE = re.compile(r'"text":"((?:[^"\\]|\\.)*)","crTimeMs"')


class Captcha(Exception):
    pass


def unescape(s):
    try:
        return json.loads('"' + s + '"')
    except ValueError:
        return s


def short(s, n=TEXT_LEN):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def collect_products():
    """Возвращает ({product_id: card_id}, {product_id: [статьи]}, [товары без id карточки])."""
    aff = json.loads(AFFILIATE.read_text(encoding="utf-8"))
    cards, articles, nocard = {}, {}, []
    for f in sorted(CONTENT.glob("*.md")):
        ids = dict.fromkeys(re.findall(r"\[\[product:([^\]]+)\]\]", f.read_text(encoding="utf-8")))
        for pid in ids:
            articles.setdefault(pid, []).append(f.stem)
            if pid in cards or pid in nocard:
                continue
            url = ((aff.get(pid) or {}).get("url", "")).split("?")[0]
            m = re.search(r"(\d+)(?:[/#]|$)", url)
            if m:
                cards[pid] = m.group(1)
            else:
                nocard.append(pid)
    return cards, articles, nocard


def fetch(card_id):
    """HTML страницы вопросов. Сетевая ошибка -> OSError, капча -> Captcha."""
    r = subprocess.run(
        ["curl", "-s", "-m", "20", "-A", UA, "-H", "Accept-Language: ru",
         f"https://market.yandex.ru/card/x/{card_id}/questions"],
        capture_output=True)
    html = r.stdout.decode("utf-8", "replace")
    if r.returncode != 0 or not html:
        raise OSError(f"curl код {r.returncode}, длина {len(html)}")
    if "showcaptcha" in html[:5000] or len(html) < MIN_HTML:
        raise Captcha(f"длина {len(html)}")
    return html


def parse(html):
    """{qid: {"text", "date", "count", "answers": [до 2 текстов]}}."""
    result = {}
    for x in QRE.finditer(html):
        qid = x.group(2)
        if qid in result:
            continue
        answers = []
        start = html.find('"' + qid + '":{"showMoreCount"')
        if start > 0:
            end = html.find('"showMoreCount"', start + 20)
            end = start + 6000 if end < 0 else min(end, start + 6000)
            for t in TRE.finditer(html, start, end):
                text = short(unescape(t.group(1)))
                if text and text not in answers:
                    answers.append(text)
        result[qid] = {
            "text": short(unescape(x.group(3))),
            "date": datetime.date.fromtimestamp(int(x.group(4)) / 1000).strftime("%Y-%m"),
            "count": int(x.group(5)),
            "answers": answers[:2],
        }
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--init", action="store_true", help="заполнить состояние текущими вопросами, без отчёта")
    ap.add_argument("--dry-run", action="store_true", help="отчёт в stdout, состояние и файлы не пишутся")
    args = ap.parse_args()

    cards, articles, nocard = collect_products()
    state = {}
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding="utf-8"))

    found = {}      # product_id -> список находок (вид, дата, вопрос, ответы)
    failed = []     # товары с сетевой ошибкой
    stopped = None  # товар, на котором поймали капчу
    checked = n_questions = new_q = new_a = 0
    first = True

    for pid, cid in cards.items():
        if not first:
            time.sleep(PAUSE)
        first = False
        try:
            qs = parse(fetch(cid))
        except OSError as e:
            failed.append(f"{pid} ({cid}): {e}")
            continue
        except Captcha as e:
            stopped = f"{pid} ({cid}): {e}"
            break
        checked += 1
        n_questions += len(qs)
        old = state.get(pid)
        # товар без состояния (новый в статьях) — только запоминаем, не считаем всё новым
        if old is not None and not args.init:
            for qid, q in qs.items():
                if qid not in old:
                    kind = "новый вопрос"
                    new_q += 1
                elif q["count"] > old[qid]:
                    kind = "новый ответ"
                    new_a += 1
                else:
                    continue
                found.setdefault(pid, []).append((kind, q["date"], q["text"], q["answers"]))
        # старые вопросы не теряем, даже если со страницы они пропали
        state[pid] = {**(old or {}), **{qid: q["count"] for qid, q in qs.items()}}

    today = datetime.date.today().isoformat()
    if args.init:
        if not args.dry_run:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"init: товаров {checked} из {len(cards)}, вопросов {n_questions}"
              f", не получено {len(failed) + len(nocard)}"
              + (f", ПРЕРВАНО (капча): {stopped}" if stopped else "")
              + ("" if args.dry_run else f"\nсостояние: {STATE}"))
        for f in failed:
            print("ошибка:", f)
        return 2 if stopped else 0

    lines = [f"# Вопросы покупателей Маркета — {today}", "",
             f"- Карточек проверено: {checked} из {len(cards)}",
             f"- Новых вопросов: {new_q}",
             f"- Новых ответов: {new_a}",
             f"- Не удалось получить: {len(failed) + len(nocard)}"]
    if stopped:
        lines.append(f"- ПРЕРВАНО из-за капчи/блокировки на товаре {stopped}; остальные не проверялись")
    lines.append("")
    if failed or nocard:
        lines.append("Не получены:")
        lines += [f"- {f}" for f in failed]
        lines += [f"- {p}: нет id карточки в affiliate.json" for p in nocard]
        lines.append("")
    if not found:
        lines += ["Новых вопросов и ответов нет", ""]
    else:
        by_article = {}
        for pid in found:
            for art in articles[pid]:
                by_article.setdefault(art, []).append(pid)
        for art in sorted(by_article):
            lines += [f"## {art}", ""]
            for pid in by_article[art]:
                lines += [f"### {pid} ({cards[pid]})", ""]
                for kind, date, text, answers in found[pid]:
                    row = f"- [{kind}] ({date}) {text}"
                    if answers:
                        row += " → " + " | ".join(answers)
                    lines.append(row)
                lines.append("")
    report = "\n".join(lines)

    if args.dry_run:
        print(report)
    else:
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / f"questions-{today}.md"
        path.write_text(report, encoding="utf-8")
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"проверено карточек {checked} из {len(cards)}, новых вопросов {new_q}, новых ответов {new_a}"
              f", не получено {len(failed) + len(nocard)}"
              + (f", ПРЕРВАНО (капча): {stopped}" if stopped else ""))
        print(f"отчёт: {path}")
    return 2 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
