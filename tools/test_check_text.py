import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_text as ct  # noqa: E402


def vals(line):
    return [m[2] for m in ct.price_mentions(line)]


def test_thousands_decimal_comma():
    assert vals("около 5,4 тыс. ₽") == [5400]
    assert vals("около 5.4 тыс. ₽") == [5400]
    assert vals("около 5 тыс. ₽") == [5000]
    assert vals("стоит 3 649 ₽") == [3649]


def test_stat_mentions():
    kinds = {(m[2], m[3]) for m in ct.stat_mentions("4.9 из 5 при 24 оценках, 75 покупок, рейтинг 4,8")}
    assert ("rating", 4.9) in kinds and ("rating", 4.8) in kinds
    assert ("reviews", 24) in kinds and ("bought", 75) in kinds
    assert not ct.stat_mentions("от 5 отзывов")


def test_stat_mismatch():
    p = {"rating": 4.9, "reviews": 24, "bought": 75}
    assert ct.stat_mismatch("rating", 4.9, False, p) is None
    assert ct.stat_mismatch("rating", 4.7, False, p)
    assert ct.stat_mismatch("reviews", 25, False, p) is None   # не больше 2 шт.
    assert ct.stat_mismatch("reviews", 40, False, p)
    assert ct.stat_mismatch("bought", 80, True, p) is None


# ---- дата цен: плейсхолдер {{prices_date}} в build.py, поле prices_checked

def _build_module():
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.path.insert(0, str(Path(__file__).parent))
    import build  # noqa: E402
    return build


def test_prices_date_placeholder():
    b = _build_module()
    meta = {"prices_checked": "2026-10-19"}
    out = b.apply_prices_date("на {{prices_date}} и на {{prices_date_text}} года", meta, "x.md")
    assert out == "на 19.10.2026 и на 19 октября 2026 года"
    import datetime
    out = b.apply_prices_date("{{prices_date}}", {"prices_checked": datetime.date(2026, 1, 5)}, "x.md")
    assert out == "05.01.2026"
    assert b.apply_prices_date("без плейсхолдера", {}, "x.md") == "без плейсхолдера"


def test_prices_date_missing_field_fails():
    import pytest
    b = _build_module()
    with pytest.raises(SystemExit):
        b.apply_prices_date("цены на {{prices_date}}", {}, "x.md")


def test_stale_prices_checked():
    from datetime import date
    art = lambda meta: {"path": Path("a.md"), "prods": [{"label": "x"}], "meta": meta}
    today = date(2026, 10, 19)
    assert ct.analyze_prices_checked([art({"prices_checked": date(2026, 10, 10)})], today) == []
    assert len(ct.analyze_prices_checked([art({"prices_checked": date(2026, 9, 1)})], today)) == 1
    assert len(ct.analyze_prices_checked([art({})], today)) == 1


# ---- один товар в нескольких статьях

def _art(name, **p):
    base = {"label": "m1", "name": "Model 1", "price": 5000, "rating": 4.8, "reviews": 20, "bought": 100,
            "material": "латунь", "pros": ["a", "b", "c"], "cons": ["x"]}
    base.update(p)
    return {"path": Path(name), "prods": [base], "lines": [], "fm_lines": 0, "meta": {}}


def test_cross_article_same_data():
    rows, warns = ct.analyze_cross_article([_art("a.md"), _art("b.md", price=5100, reviews=21)])
    assert rows == [] and warns == []


def test_cross_article_mismatch():
    rows, warns = ct.analyze_cross_article(
        [_art("a.md"), _art("b.md", price=6000, rating=4.5, reviews=30, material="сталь")])
    fields = {r[1] for r in rows}
    assert fields == {"price", "rating", "reviews", "material"}
    assert all(r[0] == "m1" and r[2] == "a.md" and r[4] == "b.md" for r in rows)


def test_cross_article_pros_warning():
    rows, warns = ct.analyze_cross_article([_art("a.md"), _art("b.md", pros=["a", "b", "d"])])
    assert rows == [] and len(warns) == 1 and warns[0][1] == "pros"


def test_cross_article_single_article_ignored():
    assert ct.analyze_cross_article([_art("a.md")]) == ([], [])


def test_set_prices_checked_and_fully_checked():
    import check_products as cp
    fm = "title: t\ndate: 2026-10-01\nupdated: 2026-10-05\nslug: s"
    out = cp.set_prices_checked(fm, "2026-10-19")
    assert "updated: 2026-10-05\nprices_checked: 2026-10-19\nslug: s" in out
    assert cp.set_prices_checked(out, "2026-10-26").count("prices_checked") == 1
    arts = [{"path": Path("a.md"), "meta": {"products": {"x": {}, "y": {}}}},
            {"path": Path("b.md"), "meta": {"products": {"x": {}}}}]
    entries = [{"label": "x", "card": {"status": "ok"}}, {"label": "y", "card": {"status": "error"}}]
    assert cp.fully_checked(arts, entries) == {Path("b.md")}
