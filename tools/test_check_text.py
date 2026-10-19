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
