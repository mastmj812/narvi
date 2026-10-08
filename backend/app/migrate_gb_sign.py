"""One-shot gunbarrel sign migration, rule v1 -> v2 — dry-run by default, --apply to write.

Rule v1 put +offset 90° clockwise of the folded [0,180) azimuth: West-ish for
plans past 135° (a 0.3° TRUE plan is 179.5° GRID -> +offset WEST) and South for
E-W units. Rule v2 (Michael, 2026-10-08; workspace rule 16; placement.cross_axis)
reads every cross-section W -> E for N-S-ish laterals and S -> N for E-W-ish
ones. The two axes are either identical or exact opposites for a given frame
azimuth, so a persisted scenario converts by pure NEGATION — no recompute, no
warehouse read:

* every inventory_well detail->legs[].gunbarrel_x_ft, and
* every recipe pin summary.generate.zones[].offset_ft (a pin is a gunbarrel
  position — un-negated, a re-save would land the row on the mirror side),

for scenarios whose header azimuth_deg flips under v2. Every scenario gets
summary.gunbarrel_rule = 2, which makes the run idempotent (stamped rows are
skipped; v2 saves stamp it themselves). Deliberately NOT a re-save: re-saving
recomputes novi_rep / categories against today's warehouse, and dropped deals'
drop-time novi_rep is the overlay's only record. updated_at is left alone — the
geometry did not change, only the sign convention it is reported in.

Writes narvi.* outside the save endpoints: --apply needs Michael's explicit go.
Verify afterwards with `python -m app.resave` (dry-run): the section-6
invariant must hold (~0 ft) on every scenario under the v2 axis.

Run from backend/:
    ..\\.venv\\Scripts\\python.exe -m app.migrate_gb_sign [--deal D] [--apply]
"""

from __future__ import annotations

import argparse
import copy
import math
import sys

from psycopg.types.json import Jsonb

from narvi.placement import GUNBARREL_RULE, cross_axis
from narvi.warehouse import get_connection


def flips(azimuth_deg: float) -> bool:
    """TRUE when the v2 cross axis is the reverse of the v1 axis for this frame
    azimuth (v1: 90° clockwise of the folded azimuth)."""
    a = math.radians(azimuth_deg % 180.0)
    v1 = (math.cos(a), -math.sin(a))
    v2 = cross_axis(azimuth_deg)
    return v1[0] * v2[0] + v1[1] * v2[1] < 0.0


def migrate_scenario(
    azimuth_deg: float | None, summary: dict | None, details: list[dict]
) -> tuple[dict | None, list[dict], dict]:
    """Pure conversion of one scenario. Returns (new summary, new details,
    stats). Already-stamped (rule >= 2) or frame-less scenarios come back
    unchanged with stats['action'] saying why."""
    stats = {"action": "", "legs": 0, "pins": 0}
    if (summary or {}).get("gunbarrel_rule", 1) >= GUNBARREL_RULE:
        stats["action"] = "already v2"
        return summary, details, stats
    if azimuth_deg is None:
        stats["action"] = "SKIP: no header azimuth (frame unknown)"
        return summary, details, stats
    new_summary = copy.deepcopy(summary) if summary is not None else {}
    new_details = copy.deepcopy(details)
    if flips(azimuth_deg):
        for d in new_details:
            for leg in d.get("legs") or []:
                if leg.get("gunbarrel_x_ft") is not None:
                    leg["gunbarrel_x_ft"] = -float(leg["gunbarrel_x_ft"])
                    stats["legs"] += 1
        for z in ((new_summary.get("generate") or {}).get("zones") or []):
            if isinstance(z, dict) and z.get("offset_ft") is not None:
                z["offset_ft"] = -float(z["offset_ft"])
                stats["pins"] += 1
        stats["action"] = "NEGATE"
    else:
        stats["action"] = "stamp only (axis unchanged)"
    new_summary["gunbarrel_rule"] = GUNBARREL_RULE
    return new_summary, new_details, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m app.migrate_gb_sign",
        description="One-shot narvi gunbarrel sign migration v1 -> v2 "
                    "(dry-run by default).")
    ap.add_argument("--deal", help="only this deal_id")
    ap.add_argument("--apply", action="store_true",
                    help="write the conversion (one transaction; writes!)")
    args = ap.parse_args(argv)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT deal_id, scenario_id, azimuth_deg, summary FROM narvi.scenario "
                + ("WHERE deal_id = %s " if args.deal else "")
                + "ORDER BY deal_id, scenario_id",
                (args.deal,) if args.deal else ())
            scenarios = cur.fetchall()
            print(f"narvi gunbarrel sign migration v1 -> v{GUNBARREL_RULE} - "
                  f"{'APPLY' if args.apply else 'DRY-RUN'} - {len(scenarios)} scenario(s)")
            totals = {"NEGATE": 0, "stamp": 0, "skip": 0, "legs": 0, "pins": 0}
            for deal_id, scenario_id, az, summary in scenarios:
                cur.execute(
                    "SELECT well_uid, detail FROM narvi.inventory_well "
                    "WHERE deal_id = %s AND scenario_id = %s ORDER BY well_uid",
                    (deal_id, scenario_id))
                wells = cur.fetchall()
                new_summary, new_details, st = migrate_scenario(
                    az, summary, [w[1] for w in wells])
                print(f"{deal_id:<32} {scenario_id:<36} az={az!s:<7} "
                      f"{st['action']:<28} legs={st['legs']:<4} pins={st['pins']}")
                if st["action"] == "NEGATE":
                    totals["NEGATE"] += 1
                elif st["action"].startswith("stamp"):
                    totals["stamp"] += 1
                else:
                    totals["skip"] += 1
                totals["legs"] += st["legs"]
                totals["pins"] += st["pins"]
                if not args.apply or new_summary is summary:
                    continue
                cur.execute(
                    "UPDATE narvi.scenario SET summary = %s "
                    "WHERE deal_id = %s AND scenario_id = %s",
                    (Jsonb(new_summary), deal_id, scenario_id))
                for (uid, _), det in zip(wells, new_details):
                    cur.execute(
                        "UPDATE narvi.inventory_well SET detail = %s WHERE well_uid = %s",
                        (Jsonb(det), uid))
        print(f"\nnegated {totals['NEGATE']} scenario(s) ({totals['legs']} legs, "
              f"{totals['pins']} pins); stamped-only {totals['stamp']}; "
              f"skipped {totals['skip']}")
        if args.apply:
            conn.commit()
            print("COMMITTED. Verify: python -m app.resave (dry-run) - section-6 "
                  "invariant ~0 ft on every scenario.")
        else:
            conn.rollback()
            print("dry-run: nothing written (re-run with --apply after the go).")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
