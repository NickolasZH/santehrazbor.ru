#!/usr/bin/env python3
"""Тесты формул калькулятора затирки: Python-эталон + те же кейсы через JS (если в системе есть node).

Запуск: .venv/bin/python tools/test_calc_zatirka.py
Только стандартная библиотека. Без node JS-часть пропускается — те же кейсы прогоняются вручную в браузере:
в консоли страницы /kalkulyator-zatirki/ выполнить CalcZatirka.calc({...}) (см. CASES ниже).
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calc_zatirka_ref as ref  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js" / "calc-zatirka.js"
NODE = shutil.which("node")

# Общие кейсы для Python и JS: входы калькулятора целиком
CASES = {
    "ce33_300x600_t9_j3": {"area": "1", "a": "30", "b": "60", "thick": "9", "joint": "3",
                           "reserve": "0", "groutKey": "ce33", "rho": ""},
    "ce33_600x600_t9_j3": {"area": "1", "a": "60", "b": "60", "thick": "9", "joint": "3",
                           "reserve": "0", "groutKey": "ce33", "rho": ""},
    "bath_default": {"area": "17,15", "a": "25", "b": "40", "thick": "8", "joint": "2",
                     "reserve": "10", "groutKey": "ce33", "rho": ""},
    "bath_epoxy": {"area": "17.15", "a": "25", "b": "40", "thick": "8", "joint": "2",
                   "reserve": "10", "groutKey": "epoxy", "rho": ""},
    "mosaic_5x5_epoxy": {"area": "4", "a": "5", "b": "5", "thick": "6", "joint": "2",
                         "reserve": "10", "groutKey": "epoxy", "rho": ""},
    "lle_20x20_t3_j1": {"area": "1", "a": "2", "b": "2", "thick": "3", "joint": "1",
                        "reserve": "0", "groutKey": "lle", "rho": ""},
    "custom_rho": {"area": "10", "a": "30", "b": "30", "thick": "8", "joint": "3",
                   "reserve": "15", "groutKey": "custom", "rho": "1,7"},
}
KEYS = ["perM2", "kgNet", "kg"]


def num(s):
    return float(str(s).replace(",", "."))


def py_calc(c):
    rho = num(c["rho"]) if c["groutKey"] == "custom" else ref.GROUTS[c["groutKey"]]["rho"]
    per = ref.grout_per_m2(num(c["a"]) * 10, num(c["b"]) * 10, num(c["joint"]), num(c["thick"]), rho)
    net = num(c["area"]) * per
    return {"perM2": per, "kgNet": net, "kg": net * (1 + num(c["reserve"]) / 100)}


class RefFormulas(unittest.TestCase):
    # ТДС Ceresit CE 33 Plus: 300×600 шов 3 -> 0,15; 600×600 шов 3 -> 0,10 кг/м²; совпадает при толщине плитки 9 мм
    def test_tds_ce33_300x600(self):
        v = py_calc(CASES["ce33_300x600_t9_j3"])["perM2"]
        self.assertAlmostEqual(v, 0.1485, places=4)
        self.assertEqual(round(v, 2), 0.15)

    def test_tds_ce33_600x600(self):
        v = py_calc(CASES["ce33_600x600_t9_j3"])["perM2"]
        self.assertAlmostEqual(v, 0.099, places=4)
        self.assertEqual(round(v, 2), 0.10)

    def test_tds_ce33_other_rows(self):
        # другие строки таблицы ТДС: 100×100 шов 2 -> 0,35 (T=8); 150×150 шов 3 -> 0,35 (T=8); 300×300 шов 3 -> 0,20 (T=9)
        self.assertEqual(round(ref.grout_per_m2(100, 100, 2, 8, 1.1), 2), 0.35)
        self.assertEqual(round(ref.grout_per_m2(150, 150, 3, 8, 1.1), 2), 0.35)
        self.assertEqual(round(ref.grout_per_m2(300, 300, 3, 9, 1.1), 2), 0.20)

    def test_tds_litokol_luxury_evo(self):
        # ТДС Litokol (ρ 1,9 восстановлена): 20×20×3 мм шов 1 -> 0,57 точно; 300×600×10 шов 3 -> 0,30; 600×600×10 шов 5 -> 0,30
        rho = ref.GROUTS["lle"]["rho"]
        self.assertEqual(round(ref.grout_per_m2(20, 20, 1, 3, rho), 2), 0.57)
        self.assertAlmostEqual(ref.grout_per_m2(300, 600, 3, 10, rho), 0.30, delta=0.03)
        self.assertAlmostEqual(ref.grout_per_m2(600, 600, 5, 10, rho), 0.30, delta=0.03)

    def test_default_bathroom(self):
        r = py_calc(CASES["bath_default"])
        self.assertAlmostEqual(r["perM2"], 0.1144, places=4)
        self.assertAlmostEqual(r["kg"], 2.158156, places=5)

    def test_epoxy_heavier_than_cement(self):
        ratio = py_calc(CASES["bath_epoxy"])["kg"] / py_calc(CASES["bath_default"])["kg"]
        self.assertAlmostEqual(ratio, 1.55 / 1.1, places=6)

    def test_mosaic_much_more_than_large_tile(self):
        self.assertGreater(ref.grout_per_m2(50, 50, 2, 6, 1.1), 4 * ref.grout_per_m2(600, 600, 2, 6, 1.1))

    def test_reserve_zero_equals_net(self):
        r = py_calc(CASES["ce33_300x600_t9_j3"])
        self.assertAlmostEqual(r["kg"], r["kgNet"])


class Combos(unittest.TestCase):
    def test_epoxy_3_4_kg(self):
        self.assertEqual(ref.best_combo(3.4, [1, 2.5, 5]), ({2.5: 1, 1: 1}, 3.5))

    def test_epoxy_exact_5(self):
        self.assertEqual(ref.best_combo(5, [1, 2.5, 5]), ({5: 1}, 5))

    def test_epoxy_6_1_kg(self):
        self.assertEqual(ref.best_combo(6.1, [1, 2.5, 5]), ({2.5: 1, 1: 4}, 6.5))

    def test_epoxy_small(self):
        self.assertEqual(ref.best_combo(0.2, [1, 2.5, 5]), ({1: 1}, 1))

    def test_tie_prefers_fewer_packs(self):
        # 7,5 кг: 5 + 2,5 (две упаковки) лучше, чем 3 × 2,5
        self.assertEqual(ref.best_combo(7.5, [1, 2.5, 5]), ({5: 1, 2.5: 1}, 7.5))

    def test_cement_2_5_packs(self):
        self.assertEqual(ref.best_combo(7.1, [2, 5]), ({2: 4}, 8))
        self.assertEqual(ref.best_combo(4.5, [2, 5]), ({5: 1}, 5))

    def test_shop_epoxy_1_and_2_5(self):
        self.assertEqual(ref.best_combo(3.04, [2.5, 1]), ({2.5: 1, 1: 1}, 3.5))

    def test_exact_pack(self):
        self.assertEqual(ref.best_combo(2.5, [1, 2.5, 5]), ({2.5: 1}, 2.5))


class Tables(unittest.TestCase):
    def test_rows(self):
        rows = ref.table_rows(1.1)
        self.assertEqual(len(rows), len(ref.TABLE_SIZES))
        label, t, vals = rows[0]
        self.assertEqual(label, "2×2")
        self.assertEqual(len(vals), len(ref.TABLE_JOINTS))


def run_js(cases):
    script = ("const c=require(%s);const cs=%s;console.log(JSON.stringify(cs.map(x=>{const r=c.calc(x);"
              "return r.ok?r:{error:Object.keys(r.errors)};})));" % (json.dumps(str(JS)), json.dumps(cases)))
    res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(res.stdout)


@unittest.skipUnless(NODE, "node не найден — JS-часть не проверяется")
class JsMatchesRef(unittest.TestCase):
    def test_cases(self):
        names = list(CASES)
        got = run_js([CASES[n] for n in names])
        for n, g in zip(names, got):
            self.assertNotIn("error", g, n)
            exp = py_calc(CASES[n])
            for k in KEYS:
                self.assertAlmostEqual(float(g[k]), float(exp[k]), places=6, msg=f"{n}.{k}")

    def test_validation(self):
        base = CASES["bath_default"]
        bad = [dict(base, joint="250"), dict(base, area="0"), dict(base, area="abc"), dict(base, area="100000"),
               dict(base, joint="20"), dict(base, a="2", b="2", joint="15", thick="6"),
               dict(base, groutKey="custom", rho=""),
               dict(base, area="1000", a="2", b="2", joint="15", thick="30")]
        got = run_js(bad)
        self.assertEqual(got[0]["error"], ["joint"])
        self.assertEqual(got[1]["error"], ["area"])
        self.assertEqual(got[2]["error"], ["area"])
        self.assertEqual(got[3]["error"], ["area"])
        self.assertEqual(got[4]["error"], ["joint"])
        self.assertNotIn("error", got[5])  # мозаика 2×2 см, шов 15 мм < 20 мм — допустимо
        self.assertEqual(got[6]["error"], ["rho"])
        self.assertEqual(got[7]["error"], ["sum"])


if __name__ == "__main__":
    if not NODE:
        print("node не найден: JS-часть пропущена (проверка JS — вручную в браузере)", file=sys.stderr)
    unittest.main(verbosity=1)
