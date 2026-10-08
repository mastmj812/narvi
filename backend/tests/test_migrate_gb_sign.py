"""One-shot v1 -> v2 gunbarrel sign migration (app.migrate_gb_sign): pure
negation for flipped frames, pins negated with the legs, idempotent via the
summary.gunbarrel_rule stamp. DB-free."""

import math

from app.migrate_gb_sign import flips, migrate_scenario
from narvi.placement import gunbarrel_offset_ft


def _v1_offset(xy, az):
    a = math.radians(az % 180.0)
    return xy[0] * math.cos(a) - xy[1] * math.sin(a)


def test_flips_matches_the_rule():
    assert not flips(0.3) and not flips(40.2) and not flips(45.0)
    assert flips(45.1) and flips(55.3) and flips(71.3) and flips(89.0)
    assert flips(90.0) and flips(161.3) and flips(179.5)
    # 179.96 rounds onto the 0° side under v2 (+E) while v1 put + West: flips
    assert flips(179.96)


def test_negation_reproduces_v2_projection():
    for az in (0.3, 40.2, 55.3, 71.3, 89.0, 90.0, 128.8, 161.3, 179.5, 179.96):
        pt = (123.0, -45.0)
        v1 = _v1_offset(pt, az)
        details = [{"legs": [{"gunbarrel_x_ft": v1}]}]
        _, out, st = migrate_scenario(az, {"mode": "generate"}, details)
        want = gunbarrel_offset_ft(pt, az, (0.0, 0.0)) / 3.280839895
        assert abs(out[0]["legs"][0]["gunbarrel_x_ft"] - want) < 1e-6, az


def test_pins_negated_and_stamped():
    summary = {"mode": "composed",
               "generate": {"zones": [{"offset_ft": None}, {"offset_ft": -660.0}]}}
    details = [{"legs": [{"gunbarrel_x_ft": 100.0}, {"gunbarrel_x_ft": -200.0}]}]
    new_s, new_d, st = migrate_scenario(71.3, summary, details)
    assert st == {"action": "NEGATE", "legs": 2, "pins": 1}
    assert new_s["generate"]["zones"][1]["offset_ft"] == 660.0
    assert new_s["generate"]["zones"][0]["offset_ft"] is None
    assert [leg["gunbarrel_x_ft"] for leg in new_d[0]["legs"]] == [-100.0, 200.0]
    assert new_s["gunbarrel_rule"] == 2
    # inputs untouched (deep copies — the JSONB shallow-copy trap)
    assert summary["generate"]["zones"][1]["offset_ft"] == -660.0
    assert details[0]["legs"][0]["gunbarrel_x_ft"] == 100.0


def test_idempotent_and_unflipped():
    new_s, new_d, st = migrate_scenario(71.3, {"gunbarrel_rule": 2}, [{"legs": [{"gunbarrel_x_ft": 5.0}]}])
    assert st["action"] == "already v2" and new_d[0]["legs"][0]["gunbarrel_x_ft"] == 5.0
    new_s, new_d, st = migrate_scenario(40.2, None, [{"legs": [{"gunbarrel_x_ft": 5.0}]}])
    assert st["action"].startswith("stamp") and new_d[0]["legs"][0]["gunbarrel_x_ft"] == 5.0
    assert new_s == {"gunbarrel_rule": 2}
    _, _, st = migrate_scenario(None, {}, [])
    assert st["action"].startswith("SKIP")
