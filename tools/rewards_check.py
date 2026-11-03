"""Проверка реферальной награды карточек Маркета (под входом на home-server).

  rewards_check.py --only метка [--only ...] | --missing | --all  [--apply]

Список уходит по ssh в ~/market-rewards/market_rewards.py; здесь только
стандартная библиотека. С --apply пишет reward_rub_<ГГГГ_ММ_ДД> в affiliate.json.
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

AFF = Path(__file__).resolve().parent.parent / "affiliate.json"
REMOTE = "~/kwork-board/.venv/bin/python ~/market-rewards/market_rewards.py"


def pick(data, only, missing, all_):
    if only:
        bad = [k for k in only if k not in data]
        if bad:
            sys.exit("нет меток: " + ", ".join(bad))
        return list(dict.fromkeys(only))
    if all_:
        return [k for k, v in data.items() if v.get("url")]
    if missing:
        return [k for k, v in data.items()
                if v.get("url") and not any(f.startswith("reward_rub_") for f in v)]
    sys.exit("нужен --only, --missing или --all")


def dump(data):
    # формат файла: отступ 2, кириллица как есть, без перевода строки в конце
    return json.dumps(data, indent=2, ensure_ascii=False)


def apply_rewards(data, rewards, day):
    key = "reward_rub_" + day.strftime("%Y_%m_%d")
    for label, rub in rewards.items():
        if rub is not None and label in data:
            data[label][key] = rub
    return key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append")
    ap.add_argument("--missing", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    data = json.loads(AFF.read_text(encoding="utf-8"))
    labels = pick(data, a.only, a.missing, a.all)
    job = [{"label": k, "url": data[k]["url"]} for k in labels]
    print("карточек: %d (на запуск не больше 40, пауза 6 с)" % len(job), file=sys.stderr)
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "home-server", REMOTE],
                       input=json.dumps(job, ensure_ascii=False),
                       capture_output=True, text=True)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        sys.exit("нет JSON от home-server:\n" + (r.stderr or r.stdout)[-500:])
    for label in labels:
        v = res["rewards"].get(label)
        print("%-40s %s" % (label, "не проверено" if v is None else v))
    if res.get("stopped"):
        print("ОСТАНОВКА: " + res["stopped"])
    if a.apply:
        key = apply_rewards(data, res["rewards"], date.today())
        AFF.write_text(dump(data), encoding="utf-8")
        print("записано в %s: %s" % (AFF.name, key))
    return 1 if res.get("stopped") else 0


if __name__ == "__main__":
    sys.exit(main())
