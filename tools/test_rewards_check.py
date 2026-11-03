import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rewards_check as rc  # noqa: E402

_p = Path(__file__).resolve().parents[2] / "tools/market-rewards/market_rewards.py"
_s = importlib.util.spec_from_file_location("market_rewards", _p)
mr = importlib.util.module_from_spec(_s)
_s.loader.exec_module(mr)


def test_reward_regex():
    assert mr.parse_reward('x"referralReward":2296,"y"') == 2296
    assert mr.parse_reward('referralReward&quot;:665,') == 665
    assert mr.parse_reward('referralReward\\":12') == 12
    assert mr.parse_reward('referralReward:5 referralReward:9') == 5
    assert mr.parse_reward('нет награды') == 0


def test_login_marker():
    assert mr.has_login('{"uid":"123456789"}')
    assert not mr.has_login('{"uid":"123"}') and not mr.has_login('{"uid":""}')


def test_jar_format():
    t = mr.netscape_jar([{"domain": ".yandex.ru", "path": "/", "secure": True,
                          "httpOnly": True, "expires": -1, "name": "a", "value": "b"}])
    assert "#HttpOnly_.yandex.ru\tTRUE\t/\tTRUE\t0\ta\tb" in t


def test_pick():
    d = {"a": {"url": "u"}, "b": {"url": "u", "reward_rub_2026_10_12": 1}}
    assert rc.pick(d, None, True, False) == ["a"]
    assert rc.pick(d, None, False, True) == ["a", "b"]
    assert rc.pick(d, ["b"], False, False) == ["b"]


def test_affiliate_format_roundtrip():
    # реальный файл должен сериализоваться байт в байт, без \n в конце
    raw = rc.AFF.read_text(encoding="utf-8")
    assert rc.dump(json.loads(raw)) == raw


def test_apply():
    d = {"a": {"url": "u"}}
    key = rc.apply_rewards(d, {"a": 7, "z": None}, date(2026, 11, 3))
    assert key == "reward_rub_2026_11_03" and d["a"][key] == 7
