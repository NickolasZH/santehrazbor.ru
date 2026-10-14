"""Python-эталон формул калькулятора затирки (используется в build.py для таблиц без JS и в тестах).

Те же формулы и константы — в static/js/calc-zatirka.js; при правке менять оба файла.
Источники плотности: ТДС Henkel Ceresit CE 33 Plus; Mapei Keracolor FF, Litokol Starlike EVO и
Litokol Litochrom Luxury EVO — восстановлены из таблиц расхода самих производителей (см. notes/calculators-plan.md).
"""
import math

import calc_plitka_ref as plitka

# Затирки: плотность, кг/дм3; фасовки, кг
GROUTS = {
    "ce33": {"rho": 1.1, "packs": [2, 5]},
    "ce40": {"rho": 1.1, "packs": [2, 5]},
    "mapei": {"rho": 1.5, "packs": [2, 5]},
    "lle": {"rho": 1.9, "packs": [2]},  # Litochrom Luxury EVO: ρ из таблицы ТДС Litokol (1,8–2,0 по строкам из-за округления)
    "epoxy": {"rho": 1.55, "packs": [1, 2.5, 5]},
    "custom": {"rho": None, "packs": [2, 5]},
}
RESERVE_DEFAULT = 10  # запас затирки по умолчанию, %

# Пресеты плитки: (A см, B см, толщина по умолчанию мм)
PRESETS = {
    "2x2": (2, 2, 6), "5x5": (5, 5, 6), "10x10": (10, 10, 7), "20x30": (20, 30, 8), "25x40": (25, 40, 8),
    "30x30": (30, 30, 8), "30x60": (30, 60, 9), "60x60": (60, 60, 10), "60x120": (60, 120, 10),
}

ceil_eps = plitka.ceil_eps
grout_per_m2 = plitka.grout_per_m2
fmt = plitka.fmt


def grout_kg(area_m2, a_cm, b_cm, joint_mm, thick_mm, rho, reserve_pct=RESERVE_DEFAULT):
    """Итого кг с запасом."""
    return area_m2 * grout_per_m2(a_cm * 10, b_cm * 10, joint_mm, thick_mm, rho) * (1 + reserve_pct / 100)


def best_combo(kg, packs):
    """Наименее избыточная комбинация фасовок -> {размер: штук}. При равном излишке — меньше упаковок,
    затем больше крупных. Перебор по числу крупных упаковок, остаток добирается мелкими."""
    packs = sorted(packs, reverse=True)
    best = None

    def rec(i, rest, chosen):
        nonlocal best
        if i == len(packs) - 1:
            n = max(0, ceil_eps(rest / packs[i]))
            counts = chosen + [n]
        else:
            for n in range(0, max(0, ceil_eps(rest / packs[i])) + 1):
                rec(i + 1, rest - n * packs[i], chosen + [n])
            return
        total = sum(c * p for c, p in zip(counts, packs))
        key = (round(total, 9), sum(counts), [-c for c in counts])
        if best is None or key < best[0]:
            best = (key, counts, total)

    rec(0, kg, [])
    return {p: c for p, c in zip(packs, best[1]) if c > 0}, best[2]


# Таблицы для noscript: размер, толщина, швы
TABLE_SIZES = [("2x2", "2×2"), ("5x5", "5×5"), ("10x10", "10×10"), ("20x30", "20×30"), ("25x40", "25×40"),
               ("30x30", "30×30"), ("30x60", "30×60"), ("60x60", "60×60"), ("60x120", "60×120")]
TABLE_JOINTS = (1.5, 2, 3, 5)


def table_rows(rho):
    """[(формат, толщина, [кг/м2 для швов 1,5/2/3/5])] без запаса."""
    rows = []
    for key, label in TABLE_SIZES:
        a, b, t = PRESETS[key]
        rows.append((label, t, [grout_per_m2(a * 10, b * 10, j, t, rho) for j in TABLE_JOINTS]))
    return rows
