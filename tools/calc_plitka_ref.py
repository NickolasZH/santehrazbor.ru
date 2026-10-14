"""Python-эталон формул калькулятора плитки (используется в build.py для таблиц без JS и в тестах).

Те же формулы и константы — в static/js/calc-plitka.js; при правке менять оба файла.
Источники: ТДС Henkel Ceresit CE 33 Plus и CM 11 Plus (см. notes/calculators-plan.md).
"""
import math

# Запас плитки на подрезку и бой: «обычно берут», у производителей цифр нет
LAYOUT_RESERVE = {"straight": 10, "diagonal": 15, "herringbone": 20}

# Затирка: плотность, кг/дм3. CE 33 Plus — ТДС Henkel; Mapei и Litokol — восстановлены из таблиц производителей
GROUT_RHO = {"ce33": 1.1, "mapei": 1.5, "lle": 1.9, "epoxy": 1.55}
GROUT_RESERVE = 1.1  # запас затирки 10 %

# Клей Ceresit CM 11 Plus: (предел большей стороны плитки, см, зуб шпателя, мм, расход кг/м2)
GLUE_TABLE = [(10, 4, 2.0), (15, 6, 2.7), (25, 8, 3.4), (30, 10, 4.2), (None, 12, 4.8)]
GLUE_BAG_KG = 25


def ceil_eps(x):
    """ceil без артефактов плавающей точки (2.0000000001 -> 2)."""
    return int(math.ceil(round(x, 9)))


def tooth_for(max_side_cm):
    """-> (зуб мм, расход кг/м2) по большей стороне плитки в см."""
    for limit, tooth, rate in GLUE_TABLE:
        if limit is None or max_side_cm <= limit:
            return tooth, rate


def glue_rate(tooth):
    for _, t, rate in GLUE_TABLE:
        if t == tooth:
            return rate
    raise ValueError(tooth)


def grout_per_m2(a_mm, b_mm, joint_mm, thick_mm, rho):
    """Расход затирки, кг/м2 (без запаса): (A+B)/(A*B) * J * T * rho."""
    return (a_mm + b_mm) / (a_mm * b_mm) * joint_mm * thick_mm * rho


def floor_area(len_m, wid_m, tub_len_m=None, tub_wid_m=None):
    """Площадь пола, м2; под ванной/поддоном плитку не кладут (вычитается). Не бывает <= 0."""
    area = len_m * wid_m
    if tub_len_m and tub_wid_m:
        area -= tub_len_m * tub_wid_m
    if area <= 0:
        raise ValueError("площадь пола после вычета ванны <= 0")
    return area


def tiles(area_m2, a_cm, b_cm, reserve_pct, box_m2=None, box_pcs=None):
    """-> (штук, коробок или None). Площадь плитки a*b без шва."""
    pcs = ceil_eps(area_m2 * (1 + reserve_pct / 100) / (a_cm / 100 * b_cm / 100))
    boxes = None
    if box_pcs:
        boxes = ceil_eps(pcs / box_pcs)
    elif box_m2:
        boxes = ceil_eps(pcs * (a_cm / 100 * b_cm / 100) / box_m2)
    return pcs, boxes


def grout_kg(area_m2, a_mm, b_mm, joint_mm, thick_mm, rho):
    return area_m2 * grout_per_m2(a_mm, b_mm, joint_mm, thick_mm, rho) * GROUT_RESERVE


def glue_kg(area_m2, tooth):
    return area_m2 * glue_rate(tooth)


def fmt(x, digits=2):
    s = f"{x:.{digits}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


# Таблицы для noscript
TABLE_FORMATS = [(20, 30), (25, 40), (30, 60), (60, 60), (60, 120)]


def grout_table_rows():
    """[(формат, шов мм, [кг/м2 для T=8,9,10])] для CE 33 Plus."""
    rows = []
    for a, b in TABLE_FORMATS:
        for j in (2, 3):
            rows.append((f"{a}×{b}", j,
                         [grout_per_m2(a * 10, b * 10, j, t, GROUT_RHO["ce33"]) for t in (8, 9, 10)]))
    return rows


def glue_table_rows():
    """[(диапазон, зуб, расход кг/м2, кг на 10 м2)]."""
    labels = ["до 10 см", "до 15 см", "до 25 см", "до 30 см", "больше 30 см"]
    return [(lab, t, r, r * 10) for lab, (_, t, r) in zip(labels, GLUE_TABLE)]
