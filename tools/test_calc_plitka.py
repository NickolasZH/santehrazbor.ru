#!/usr/bin/env python3
"""Тесты формул калькулятора плитки: Python-эталон + те же кейсы через JS (если в системе есть node).

Запуск: python tools/test_calc_plitka.py
Только стандартная библиотека.
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calc_plitka_ref as ref  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js" / "calc-plitka.js"
NODE = shutil.which("node")

# Общие кейсы для Python и JS: входы калькулятора целиком
CASES = {
    "bath_default": {  # типовая ванная: пол+стены 1,7×1,5, h 2,5, дверь 0,7×2,0, 25×40, шов 2
        "mode": "both", "len": "1,7", "wid": "1.5", "hgt": "2,5", "openings": [{"w": "0,7", "h": "2"}],
        "a": "25", "b": "40", "thick": "8", "joint": "2", "boxKind": "none", "boxVal": "",
        "reserve": "10", "groutKey": "ce33", "rho": "", "tooth": ""},
    "floor_30x30": {  # пол 1,7×1,5, плитка 30×30, 10 %
        "mode": "floor", "len": "1.7", "wid": "1.5", "hgt": "", "openings": [],
        "a": "30", "b": "30", "thick": "8", "joint": "2", "boxKind": "pcs", "boxVal": "10",
        "reserve": "10", "groutKey": "ce33", "rho": "", "tooth": ""},
    "big_format_epoxy": {
        "mode": "walls", "len": "2", "wid": "1,5", "hgt": "2,4", "openings": [{"w": "0,8", "h": "2"}],
        "a": "60", "b": "120", "thick": "10", "joint": "3", "boxKind": "m2", "boxVal": "1,44",
        "reserve": "20", "groutKey": "epoxy", "rho": "", "tooth": "10"},
    "bath_3walls": {  # ванная 1,7×1,5: 3 стены (1,7 + 1,5 + 1,7) × 2,5, дверь 0,7×2,0
        "mode": "both", "wallMode": "sel", "len": "1,7", "wid": "1.5", "hgt": "",
        "walls": [{"l": "1,7", "h": "2,5"}, {"l": "1,5", "h": "2,5"}, {"l": "1,7", "h": "2,5"}],
        "openings": [{"w": "0,7", "h": "2"}],
        "a": "25", "b": "40", "thick": "8", "joint": "2", "boxKind": "none", "boxVal": "",
        "reserve": "10", "groutKey": "ce33", "rho": "", "tooth": ""},
    "apron_2walls": {  # фартук: 2,4×0,6 + 0,6×0,6, только стены
        "mode": "walls", "wallMode": "sel", "len": "", "wid": "", "hgt": "",
        "walls": [{"l": "2,4", "h": "0,6"}, {"l": "0,6", "h": "0,6"}], "openings": [],
        "a": "30", "b": "60", "thick": "9", "joint": "2", "boxKind": "none", "boxVal": "",
        "reserve": "10", "groutKey": "ce33", "rho": "", "tooth": ""},
    "bath_perimeter_explicit": {  # явный wallMode=all — как bath_default
        "mode": "both", "wallMode": "all", "len": "1,7", "wid": "1.5", "hgt": "2,5", "openings": [{"w": "0,7", "h": "2"}],
        "a": "25", "b": "40", "thick": "8", "joint": "2", "boxKind": "none", "boxVal": "",
        "reserve": "10", "groutKey": "ce33", "rho": "", "tooth": ""},
}
KEYS = ["area", "pcs", "boxes", "groutPerM2", "groutKg", "tooth", "glueRate", "glueKg", "glueBags"]


def py_calc(c):
    """Расчёт эталоном; повторяет логику calc() в JS для валидного ввода."""
    num = lambda s: float(str(s).replace(",", "."))  # noqa: E731
    mode = c["mode"]
    floor = num(c["len"]) * num(c["wid"]) if mode in ("floor", "both") else 0
    walls = opening = 0
    if mode in ("walls", "both"):
        if c.get("wallMode") == "sel":
            walls = ref.walls_area([(num(w["l"]), num(w["h"])) for w in c["walls"]])
        else:
            walls = ref.walls_area(None, num(c["len"]), num(c["wid"]), num(c["hgt"]))
        opening = sum(num(o["w"]) * num(o["h"]) for o in c["openings"])
    area = floor + walls - opening
    a, b = num(c["a"]), num(c["b"])
    pcs, boxes = ref.tiles(
        area, a, b, num(c["reserve"]),
        box_m2=num(c["boxVal"]) if c["boxKind"] == "m2" else None,
        box_pcs=num(c["boxVal"]) if c["boxKind"] == "pcs" else None)
    rho = ref.GROUT_RHO["epoxy" if c["groutKey"] == "epoxy" else "ce33"]
    per = ref.grout_per_m2(a * 10, b * 10, num(c["joint"]), num(c["thick"]), rho)
    tooth = int(num(c["tooth"])) if c["tooth"] else ref.tooth_for(max(a, b))[0]
    gkg = area * per * ref.GROUT_RESERVE
    gl = area * ref.glue_rate(tooth)
    return {"area": area, "pcs": pcs, "boxes": boxes, "groutPerM2": per, "groutKg": gkg,
            "tooth": tooth, "glueRate": ref.glue_rate(tooth), "glueKg": gl,
            "glueBags": ref.ceil_eps(gl / ref.GLUE_BAG_KG)}


class RefFormulas(unittest.TestCase):
    def test_grout_ce33_300x600_t9_j3(self):
        self.assertAlmostEqual(ref.grout_per_m2(300, 600, 3, 9, 1.1), 0.15, delta=0.01)

    def test_grout_ce33_600x600_t10_j3(self):
        self.assertAlmostEqual(ref.grout_per_m2(600, 600, 3, 10, 1.1), 0.11, delta=0.01)

    def test_glue_tooth_by_size(self):
        self.assertEqual(ref.tooth_for(10)[0], 4)
        self.assertEqual(ref.tooth_for(10.5)[0], 6)
        self.assertEqual(ref.tooth_for(15)[0], 6)
        self.assertEqual(ref.tooth_for(25), (8, 3.4))
        self.assertEqual(ref.tooth_for(30), (10, 4.2))
        self.assertEqual(ref.tooth_for(40), (12, 4.8))
        self.assertEqual(ref.tooth_for(120), (12, 4.8))

    def test_tiles_floor_30x30(self):
        # 1,7 × 1,5 = 2,55 м2; с запасом 10 % = 2,805; / 0,09 = 31,17 -> 32
        pcs, boxes = ref.tiles(2.55, 30, 30, 10, box_pcs=10)
        self.assertEqual(pcs, 32)
        self.assertEqual(boxes, 4)

    def test_tiles_exact_no_float_artifact(self):
        # ровно 100 плиток 10×10 на 1 м2 без запаса: не должно стать 101
        self.assertEqual(ref.tiles(1.0, 10, 10, 0)[0], 100)

    def test_boxes_by_m2(self):
        pcs, boxes = ref.tiles(10, 60, 60, 10, box_m2=1.44)
        self.assertEqual(pcs, 31)
        self.assertEqual(boxes, 8)  # 31 * 0,36 / 1,44 = 7,75

    def test_default_bathroom(self):
        r = py_calc(CASES["bath_default"])
        # пол 2,55 + стены 2*(3,2)*2,5 = 16 - дверь 1,4 = 17,15
        self.assertAlmostEqual(r["area"], 17.15, places=6)
        self.assertEqual(r["pcs"], 189)  # 17,15*1,1/0,1 = 188,65
        self.assertEqual(r["tooth"], 12)  # большая сторона 40 см > 30


class SelectedWalls(unittest.TestCase):
    def test_three_walls_bathroom(self):
        r = py_calc(CASES["bath_3walls"])
        # пол 2,55 + (1,7+1,5+1,7)*2,5 = 12,25 - дверь 1,4 = 13,4
        self.assertAlmostEqual(r["area"], 13.4, places=6)

    def test_apron(self):
        r = py_calc(CASES["apron_2walls"])
        self.assertAlmostEqual(r["area"], 2.4 * 0.6 + 0.36, places=6)  # 1,8

    def test_perimeter_unchanged(self):
        self.assertAlmostEqual(py_calc(CASES["bath_perimeter_explicit"])["area"], 17.15, places=6)


@unittest.skipUnless(NODE, "node не найден — JS-часть не проверяется")
class JsMatchesRef(unittest.TestCase):
    def test_cases(self):
        script = (
            "const c=require(%s);const cases=%s;const out={};"
            "for(const k in cases){const r=c.calc(cases[k]);out[k]=r.ok?r:{error:r.errors};}"
            "console.log(JSON.stringify(out));" % (json.dumps(str(JS)), json.dumps(CASES)))
        res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
        js = json.loads(res.stdout)
        for name, case in CASES.items():
            exp = py_calc(case)
            got = js[name]
            self.assertNotIn("error", got, name)
            for k in KEYS:
                self.assertAlmostEqual(float(got[k]), float(exp[k]), places=6, msg=f"{name}.{k}")

    def test_validation(self):
        bad = dict(CASES["bath_default"], joint="250")  # шов не меньше плитки
        zero = dict(CASES["bath_default"], len="0")
        text = dict(CASES["bath_default"], wid="abc")
        huge = dict(CASES["bath_default"], openings=[{"w": "5", "h": "5"}] * 3)
        script = (
            "const c=require(%s);const cs=%s;"
            "console.log(JSON.stringify(cs.map(x=>{const r=c.calc(x);return [r.ok,Object.keys(r.errors)];})));"
            % (json.dumps(str(JS)), json.dumps([bad, zero, text, huge])))
        res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
        got = json.loads(res.stdout)
        self.assertEqual(got[0], [False, ["joint"]])
        self.assertEqual(got[1], [False, ["len"]])
        self.assertEqual(got[2], [False, ["wid"]])
        self.assertEqual(got[3][0], False)
        self.assertIn("openings", got[3][1])

    def test_walls_validation(self):
        base = CASES["bath_3walls"]
        bad_row = dict(base, walls=[{"l": "1,7", "h": "2,5"}, {"l": "abc", "h": "2,5"}])
        empty = dict(base, walls=[])
        big_open = dict(base, openings=[{"w": "5", "h": "5"}])
        script = (
            "const c=require(%s);const cs=%s;"
            "console.log(JSON.stringify(cs.map(x=>{const r=c.calc(x);return [r.ok,Object.keys(r.errors)];})));"
            % (json.dumps(str(JS)), json.dumps([bad_row, empty, big_open])))
        res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
        got = json.loads(res.stdout)
        self.assertEqual(got[0], [False, ["wall1"]])
        self.assertEqual(got[1], [False, ["walls"]])
        self.assertEqual(got[2], [False, ["openings"]])


if __name__ == "__main__":
    if not NODE:
        print("node не найден: JS-часть пропущена (проверка JS — вручную в браузере)", file=sys.stderr)
    unittest.main(verbosity=1)
