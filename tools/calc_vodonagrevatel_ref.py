"""Python-эталон формул калькулятора водонагревателя (используется в build.py для таблиц без JS и в тестах).

Те же формулы и константы — в static/js/calc-vodonagrevatel.js; при правке менять оба файла.
Источники: СП 30.13330.2020 прил. А (табл. А.1 — расход воды приборами, А.2 — суточная норма);
физика нагрева: теплоёмкость воды 1,163 Вт·ч/(л·К).
"""
import math

STANDARD_VOLUMES = [30, 50, 80, 100, 120, 150, 200]  # типовой ряд объёмов бытовых накопителей, л
SINK_FLOW = 7.2             # л/мин, мойка со смесителем 0,12 л/с (СП 30.13330.2020, табл. А.1)
DAILY_PER_PERSON = 70       # л горячей воды на жителя в сутки (СП 30.13330.2020, табл. А.2)
WATER_CAPACITY = 1.163      # Вт·ч/(л·К)
VOLTAGE = 230               # В
BATH_FLOW = 15              # л/мин, ванна со смесителем 0,25 л/с (СП 30.13330.2020, табл. А.1)
SMALL_TANK_LIMIT = 15       # л: ниже — хватит малого бака/проточного под мойку
TABLE_PEOPLE = (1, 2, 3, 4, 5, 6)
TABLE_HEAT_VOLUMES = (30, 50, 80, 100)
TABLE_HEAT_POWERS = (1.5, 2, 2.5)
EPS = 1e-9


def half_up(x):
    """Округление «от половины вверх» (одинаково в Python и JS; round() в Python — банковское)."""
    return math.floor(x + 0.5 + EPS)


def mix_volume(people, minutes, flow, bath, bath_l, dish_min):
    """Объём смешанной (тёплой) воды за вечер, л."""
    return people * minutes * flow + (bath_l if bath else 0) + dish_min * SINK_FLOW


def tank_need(mix_l, t_mix, t_hot, t_cold):
    """Сколько нужно горячей воды (температуры бака), л: горячую разбавляют холодной."""
    return mix_l * (t_mix - t_cold) / (t_hot - t_cold)


def peak_minutes(people, minutes, pause, bath, bath_l, dish_min):
    """Длительность пика, мин: души подряд, перерывы между ними, посуда, набор ванны (15 л/мин)."""
    return people * minutes + (people - 1) * pause + dish_min + (bath_l / BATH_FLOW if bath else 0)


def reheat_per_hour(power_kw, t_hot, t_cold):
    """Сколько литров воды ТЭН нагревает за час с t_cold до t_hot."""
    return power_kw * 1000 / (WATER_CAPACITY * (t_hot - t_cold))


def reheat_volume(power_kw, peak_min, t_hot, t_cold):
    """Догрев за время пика, л воды температуры бака."""
    return power_kw * 1000 * peak_min / 60 / (WATER_CAPACITY * (t_hot - t_cold))


def recommend(need_l):
    """Ближайший стандартный объём вверх; None, если больше 200 л."""
    for v in STANDARD_VOLUMES:
        if need_l <= v + EPS:
            return v
    return None


def heat_minutes(volume_l, t_hot, t_cold, power_kw):
    """Время нагрева бака от холодной воды, целых минут (без теплопотерь)."""
    return half_up(WATER_CAPACITY * volume_l * (t_hot - t_cold) / (power_kw * 1000) * 60)


def current_amps(power_kw):
    return power_kw * 1000 / VOLTAGE


def shop_group(rec):
    """Объём группы товаров, которую показываем: до 100 л — свой, выше (и при > 200 л) — 100 л."""
    if rec is None or rec > 100:
        return 100
    return rec


def calc(people, minutes, flow, bath, bath_l, dish_min, t_mix, t_hot, t_cold, power_kw, pause=0, reheat=True):
    mix = mix_volume(people, minutes, flow, bath, bath_l, dish_min)
    hot = tank_need(mix, t_mix, t_hot, t_cold)
    peak = peak_minutes(people, minutes, pause, bath, bath_l, dish_min)
    dog = reheat_volume(power_kw, peak, t_hot, t_cold) if reheat else 0.0
    need = max(hot - dog, 0.0)
    rec = recommend(need)
    return {
        "mix": mix, "hot": hot, "peak_min": peak, "reheat": dog, "need": need, "rec": rec,
        "per_hour": reheat_per_hour(power_kw, t_hot, t_cold),
        "small": need <= SMALL_TANK_LIMIT + EPS,
        "heat_min": heat_minutes(rec, t_hot, t_cold, power_kw) if rec else None,
        "daily": DAILY_PER_PERSON * people,
        "amps": current_amps(power_kw),
        "group": shop_group(rec),
    }


def fmt(x, d=0):
    s = f"{x:.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def fmt_hm(minutes):
    h, m = divmod(int(minutes), 60)
    return f"{h} ч {m} мин" if h else f"{m} мин"


def people_table():
    """[(людей, нужно без ванны, рек. без ванны, нужно с ванной, рек. с ванной)] — душ 8 мин, 7,2 л/мин, 40/60/5, 2 кВт, перерыв 0, с догревом."""
    rows = []
    for n in TABLE_PEOPLE:
        a = calc(n, 8, 7.2, False, 150, 0, 40, 60, 5, 2)
        b = calc(n, 8, 7.2, True, 150, 0, 40, 60, 5, 2)
        rows.append((n, a["need"], a["rec"], b["need"], b["rec"]))
    return rows


def heat_table():
    """[(объём, [минуты при 1,5 / 2 / 2,5 кВт])] — нагрев 5 -> 60 °C."""
    return [(v, [heat_minutes(v, 60, 5, p) for p in TABLE_HEAT_POWERS]) for v in TABLE_HEAT_VOLUMES]
