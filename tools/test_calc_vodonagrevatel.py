#!/usr/bin/env python3
"""Тесты формул калькулятора водонагревателя: Python-эталон + те же кейсы через JS (если в системе есть node).

Запуск: python tools/test_calc_vodonagrevatel.py
Без node JS-часть пропускается — те же кейсы прогоняются вручную в браузере:
в консоли страницы /kalkulyator-vodonagrevatelya/ выполнить CalcVodonagrevatel.calc({...}) (входы — см. CASES).
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calc_vodonagrevatel_ref as ref  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js" / "calc-vodonagrevatel.js"
NODE = shutil.which("node")

BASE = {"people": "3", "minutes": "8", "flow": "7,2", "bath": False, "bathL": "150", "dish": "0",
        "tMix": "40", "tHot": "60", "tCold": "5", "power": "2", "pause": "0", "reheat": True}


def case(**kw):
    c = dict(BASE)
    c.update(kw)
    return c


CASES = {
    "default3": case(),
    "one_5min": case(people="1", minutes="5"),
    "one_default": case(people="1"),
    "bath3": case(bath=True),
    "huge6_bath": case(people="6", bath=True),
    "dish": case(people="2", dish="10"),
    "hot75": case(tHot="75"),
    "hot50_cold10": case(tHot="50", tCold="10", tMix="38"),
    "power3": case(power="3"),
    "tiny": case(people="1", minutes="1", flow="3"),
    "no_reheat": case(reheat=False),
    "pause10": case(pause="10"),
    "bath_reheat": case(bath=True, people="2"),
    "dish_pause": case(people="2", dish="10", pause="5"),
}


def py_calc(c):
    def f(k):
        return float(str(c[k]).replace(",", "."))
    return ref.calc(int(f("people")), f("minutes"), f("flow"), c["bath"], f("bathL"), f("dish"),
                    f("tMix"), f("tHot"), f("tCold"), f("power"), f("pause"), c["reheat"])


class Formulas(unittest.TestCase):
    def test_default_three_people(self):
        r = py_calc(CASES["default3"])
        self.assertAlmostEqual(r["mix"], 172.8, places=6)
        self.assertAlmostEqual(r["hot"], 109.9636, places=3)
        self.assertAlmostEqual(r["peak_min"], 24, places=6)
        self.assertAlmostEqual(r["reheat"], 12.5068, places=3)
        self.assertAlmostEqual(r["need"], 97.4568, places=3)
        self.assertEqual(r["rec"], 100)
        self.assertEqual(r["group"], 100)

    def test_no_reheat_as_before(self):
        r = py_calc(CASES["no_reheat"])
        self.assertEqual(r["reheat"], 0)
        self.assertAlmostEqual(r["need"], 109.9636, places=3)
        self.assertEqual(r["rec"], 120)

    def test_pause_lengthens_peak(self):
        r = py_calc(CASES["pause10"])
        self.assertAlmostEqual(r["peak_min"], 44, places=6)
        self.assertAlmostEqual(r["need"], 109.9636 - 2000 * 44 / 60 / (1.163 * 55), places=3)

    def test_per_hour(self):
        self.assertAlmostEqual(py_calc(CASES["default3"])["per_hour"], 31.267, places=3)

    def test_one_person_short_shower(self):
        r = py_calc(case(people="1", minutes="5"))
        self.assertAlmostEqual(r["hot"], 22.909, places=3)
        self.assertEqual(r["rec"], 30)

    def test_one_person_default(self):
        r = py_calc(CASES["one_default"])
        self.assertAlmostEqual(r["hot"], 36.6545, places=3)
        self.assertAlmostEqual(r["need"], 36.6545 - 2000 * 8 / 60 / (1.163 * 55), places=3)
        self.assertEqual(r["rec"], 50)

    def test_bath_peak_uses_15_lpm(self):
        r = py_calc(CASES["bath_reheat"])
        self.assertAlmostEqual(r["peak_min"], 2 * 8 + 150 / 15, places=6)
        self.assertEqual(r["rec"], 200)

    def test_bath_three_people(self):
        r = py_calc(CASES["bath3"])
        self.assertAlmostEqual(r["mix"], 322.8, places=6)
        self.assertAlmostEqual(r["hot"], 205.418, places=2)
        self.assertAlmostEqual(r["peak_min"], 34, places=6)
        self.assertEqual(r["rec"], 200)
        self.assertIsNone(py_calc(case(bath=True, reheat=False))["rec"])

    def test_over_200(self):
        self.assertIsNone(py_calc(case(people="6", bath=True, reheat=False))["rec"])
        self.assertIsNone(py_calc(case(people="10", bath=True))["rec"])
        self.assertIsNone(py_calc(case(people="10", bath=True))["heat_min"])

    def test_need_not_negative(self):
        r = py_calc(case(people="1", minutes="60", flow="1", power="3", tHot="50"))
        self.assertGreater(r["reheat"], r["hot"])
        self.assertEqual(r["need"], 0)
        self.assertEqual(r["rec"], 30)
        self.assertTrue(r["small"])

    def test_dishes_and_pause(self):
        r = py_calc(CASES["dish_pause"])
        self.assertAlmostEqual(r["mix"], 2 * 8 * 7.2 + 72, places=6)
        self.assertAlmostEqual(r["peak_min"], 2 * 8 + 5 + 10, places=6)
        self.assertEqual(r["rec"], 120)

    def test_hotter_tank_needs_less(self):
        self.assertAlmostEqual(py_calc(CASES["hot75"])["hot"], 172.8 * 35 / 70, places=6)
        self.assertLess(py_calc(CASES["hot75"])["need"], py_calc(CASES["default3"])["need"])

    def test_other_temps(self):
        r = py_calc(CASES["hot50_cold10"])
        self.assertAlmostEqual(r["hot"], 172.8 * 28 / 40, places=6)
        self.assertEqual(r["rec"], 120)

    def test_small(self):
        r = py_calc(CASES["tiny"])
        self.assertTrue(r["small"])
        self.assertEqual(r["rec"], 30)

    def test_boundary_exactly_standard(self):
        self.assertEqual(ref.recommend(100), 100)
        self.assertEqual(ref.recommend(100.0000000001), 100)
        self.assertEqual(ref.recommend(100.001), 120)
        self.assertEqual(ref.recommend(200), 200)
        self.assertIsNone(ref.recommend(200.5))
        self.assertEqual(ref.recommend(0.5), 30)

    def test_heat_time(self):
        # 120 л, 5 -> 60 °C, 2 кВт: 1,163 * 120 * 55 / 2000 = 3,838 ч = 230 мин
        self.assertEqual(ref.heat_minutes(120, 60, 5, 2), 230)
        self.assertEqual(py_calc(CASES["default3"])["heat_min"], 192)
        self.assertEqual(ref.heat_minutes(80, 60, 5, 2), 154)
        self.assertEqual(ref.fmt_hm(230), "3 ч 50 мин")
        self.assertEqual(ref.fmt_hm(45), "45 мин")

    def test_more_power_faster(self):
        self.assertLess(py_calc(CASES["power3"])["heat_min"], py_calc(CASES["default3"])["heat_min"])

    def test_amps_and_daily(self):
        self.assertAlmostEqual(ref.current_amps(2), 8.6957, places=3)
        self.assertEqual(py_calc(CASES["default3"])["daily"], 210)

    def test_tables(self):
        self.assertEqual([r[2] for r in ref.people_table()], [50, 80, 100, 150, 200, 200])
        self.assertEqual(len(ref.heat_table()), 4)

    def test_half_up(self):
        self.assertEqual(ref.half_up(2.5), 3)
        self.assertEqual(ref.half_up(3.5), 4)
        self.assertEqual(ref.half_up(2.4999), 2)


def run_js(cases):
    code = ("const m=require(process.argv[1]);const cs=JSON.parse(process.argv[2]);"
            "console.log(JSON.stringify(cs.map(c=>m.calc(c))));")
    out = subprocess.run([NODE, "-e", code, str(JS), json.dumps(cases)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node не найден")
class JsMatchesPython(unittest.TestCase):
    def test_same_results(self):
        names = list(CASES)
        got = run_js([CASES[n] for n in names])
        for n, g in zip(names, got):
            p = py_calc(CASES[n])
            self.assertTrue(g.get("ok"), n)
            self.assertAlmostEqual(g["need"], p["need"], places=6, msg=n)
            self.assertAlmostEqual(g["reheat"], p["reheat"], places=6, msg=n)
            self.assertAlmostEqual(g["peakMin"], p["peak_min"], places=6, msg=n)
            self.assertAlmostEqual(g["perHour"], p["per_hour"], places=6, msg=n)
            self.assertEqual(g["rec"], p["rec"], n)
            self.assertEqual(g["heatMin"], p["heat_min"], n)
            self.assertEqual(g["group"], p["group"], n)

    def test_errors(self):
        got = run_js([case(people="0"), case(people="abc"), case(tHot="40"), case(tMix="50"),
                      case(bath=True, bathL="0"), case(tCold="45"), case(pause="61"), case(pause="-1")])
        self.assertIn("people", got[0]["errors"])
        self.assertIn("people", got[1]["errors"])
        self.assertIn("tHot", got[2]["errors"])
        self.assertIn("tMix", got[3]["errors"])
        self.assertIn("bathL", got[4]["errors"])
        self.assertIn("tCold", got[5]["errors"])
        self.assertIn("pause", got[6]["errors"])
        self.assertIn("pause", got[7]["errors"])


if __name__ == "__main__":
    if not NODE:
        print("node не найден: JS-часть пропущена (проверка JS — вручную в браузере)", file=sys.stderr)
    unittest.main(verbosity=1)
