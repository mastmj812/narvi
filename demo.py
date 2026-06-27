"""Slice-1 demo: generate single laterals on a parcel + render a plan-view PNG.

    python demo.py                          # synthetic 1-mile section
    python demo.py deal.zip                 # a single-parcel shapefile (dissolved)
    python demo.py deals.zip "hecker"       # one named parcel from a multi-deal bundle
    python demo.py deals.zip "hecker" 80    # ...with an explicit azimuth (else auto)
    python demo.py deals.zip "hecker" uturn # ...as U-turn wells (else single)
    python demo.py winerack uturn           # multi-zone wine-rack + gun-barrel cross-section
    python demo.py deals.zip "hecker" winerack warehouse  # zones from the warehouse (real TVDs)
    python demo.py deals.zip "hecker" geojson  # also write a map-ready GeoJSON (WGS84)
    python demo.py deals.zip                # list the deal names in a bundle

Tweak the ScenarioParams below to explore spacing / azimuth / setback.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import matplotlib

matplotlib.use("Agg")

from narvi import (
    ScenarioParams,
    Zone,
    generate_scenario,
    generate_wine_rack,
    load_named_parcels,
    load_parcel_zip,
    scenario_geojson,
    synthetic_section,
)
from narvi.viz import gunbarrel_figure, planview_figure

# A placeholder Delaware bench stack for the wine-rack demo (TVDs are parameters
# unless `warehouse` mode is on, which sources median landing TVD per
# formation_blueox from curated.wells_enriched in the AOI).
_DEMO_ZONES = [Zone("AVA_2", 9500), Zone("BS2_S", 10500), Zone("WCA_1", 11500), Zone("WCA_2", 11700)]
# benches requested when sourcing zones from the warehouse (shallow -> deep Delaware)
_WAREHOUSE_STACK = ["AVA_0", "BS2_S", "BS3_C", "WCXY", "WCA_1", "WCA_2", "WCB_1", "WCC"]


def _save_planview(parcel, window, wells, path: str, title: str) -> None:
    fig = planview_figure(parcel, window, wells, f"{title} — {len(wells)} laterals")
    fig.savefig(path, dpi=110, bbox_inches="tight")
    print(f"  wrote {path}")


def _save_gunbarrel(wells, path: str, title: str) -> None:
    fig = gunbarrel_figure(wells, title)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    print(f"  wrote {path}")


def _save_geojson(parcel, window, wells, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(scenario_geojson(parcel, window, wells), fh)
    print(f"  wrote {path}")


def _save_scenario(parcel, params, wells, summary, label: str) -> None:
    """Persist a generated scenario to the warehouse (narvi schema) and echo the
    deal's saved scenarios."""
    from narvi import persist
    from narvi.warehouse import get_connection

    deal_id = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "demo"
    scenario_id = f"{params.well_type}_{params.objective}"
    conn = get_connection()
    try:
        persist.apply_schema(conn)
        n = persist.save_scenario(conn, deal_id, scenario_id, parcel, params, wells,
                                  summary=summary, name=label)
        print(f"saved {n} wells -> narvi.scenario ({deal_id} / {scenario_id})")
        for s in persist.list_scenarios(conn, deal_id):
            print(f"  [{s['scenario_id']}] {s['total_wells']} wells, "
                  f"{s['total_completed_ft']:,.0f} ft completed, az {s['azimuth_deg']}")
    finally:
        conn.close()


def main() -> None:
    args = list(sys.argv[1:])
    winerack = "winerack" in args
    if winerack:
        args.remove("winerack")
    warehouse = "warehouse" in args
    if warehouse:
        args.remove("warehouse")
    save = "save" in args
    if save:
        args.remove("save")
    geojson = "geojson" in args
    if geojson:
        args.remove("geojson")
    maxcount = "maxcount" in args
    if maxcount:
        args.remove("maxcount")
    objective = "max_count" if maxcount else "max_lateral"
    well_type = "single"
    for wt in ("uturn", "single"):
        if wt in args:
            well_type = wt
            args.remove(wt)
            break
    azimuth = None
    if args:  # a trailing numeric arg is an explicit azimuth override
        try:
            azimuth = float(args[-1])
            args = args[:-1]
        except ValueError:
            pass

    if not args:
        parcel = synthetic_section()
        label = "synthetic 1-mile section"
    else:
        data = open(args[0], "rb").read()
        if len(args) > 1:  # named parcel from a multi-deal bundle
            parcels = load_named_parcels(data)
            want = args[1].strip().lower()
            key = (next((k for k in parcels if k.lower() == want), None)
                   or next((k for k in parcels if want in k.lower()), None))
            if key is None:
                print(f"'{args[1]}' not found. deals in bundle:")
                for k in sorted(parcels):
                    print(f"  - {k}")
                return
            parcel, label = parcels[key], key
        else:
            parcel, label = load_parcel_zip(data), os.path.basename(args[0])

    if winerack:
        spacing = 1400.0 if well_type == "uturn" else 880.0  # U-turns need >= 990 leg-to-leg
        base = ScenarioParams(formation="", target_tvd_ft=0.0, azimuth_deg=azimuth,
                              well_type=well_type, objective=objective, spacing_ft=spacing,
                              setback_ft=200, min_lateral_ft=4000)
        zones = _DEMO_ZONES
        if warehouse:  # source real median landing TVDs + the section-grid azimuth
            from narvi.warehouse import (
                get_connection,
                lateral_azimuth_stats,
                zones_from_warehouse,
            )
            conn = get_connection()
            try:
                zones, stats = zones_from_warehouse(
                    conn, parcel, _WAREHOUSE_STACK, buffer_ft=5280.0, split_multimodal=True)
                az_stats = lateral_azimuth_stats(conn, parcel, buffer_ft=5280.0)
            finally:
                conn.close()
            print("warehouse TVD sourcing:")
            for st in stats:
                print(f"  {st.note}")
            print(f"warehouse azimuth: {az_stats.note}")
            if azimuth is None and az_stats.confident:  # adopt the grid azimuth
                base = replace(base, azimuth_deg=az_stats.azimuth_deg)
                print(f"  -> using grid azimuth {az_stats.azimuth_deg:.1f}°")
            if not zones:
                print("no benches with sufficient control in the AOI; aborting.")
                return
        wells, window, rep = generate_wine_rack(parcel, base, zones)
        print(f"parcel: {label}  ({parcel.area / 4046.8564224:.0f} ac)")
        print(f"wine-rack: {rep.note}")
        for z in rep.zones:
            print(f"  {z.formation:6} @ {z.target_tvd_ft:>6.0f} ft TVD: {z.wells:2} wells / {z.legs:2} legs  "
                  f"(stagger {z.stagger_offset_ft:.0f} ft)")
        tag = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") + f"_winerack_{well_type}"
        d = os.path.dirname(__file__)
        _save_planview(parcel, window, wells, os.path.join(d, f"planview_{tag}.png"), f"{label} wine-rack ({well_type})")
        _save_gunbarrel(wells, os.path.join(d, f"gunbarrel_{tag}.png"), f"{label} wine-rack — gun-barrel")
        if geojson:
            _save_geojson(parcel, window, wells, os.path.join(d, f"scenario_{tag}.geojson"))
        if save:
            _save_scenario(parcel, base, wells, asdict(rep), label)
        return

    p = ScenarioParams(
        formation="WCA_1", target_tvd_ft=11500, azimuth_deg=azimuth, well_type=well_type,
        objective=objective, spacing_ft=880, setback_ft=200, min_lateral_ft=4000,
    )
    wells, window, feas = generate_scenario(parcel, p)

    title = f"{label} ({well_type})" + (f"  az {azimuth:.0f}°" if azimuth is not None else "")
    print(f"parcel: {label}  ({parcel.area / 4046.8564224:.0f} ac)")
    print(f"feasibility: {feas.note}")
    print(f"  {feas.placed} wells / {feas.legs} legs  "
          f"completed={feas.total_completed_ft:,.0f} ft  drilled={feas.total_drilled_ft:,.0f} ft")
    for w in wells:
        legs_str = " + ".join(f"{leg.length_ft:,.0f}" for leg in w.legs)
        extra = (f"  turn R={w.turn.radius_ft:.0f}ft DLS={w.turn.dls_deg_per_100ft}°/100ft"
                 if w.turn else "")
        print(f"  {w.well_name}  {w.well_type:6}  legs[{legs_str}] ft  "
              f"completed={w.completed_lateral_ft:>7,.0f}{extra}")
    tag = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") + f"_{well_type}"
    if azimuth is not None:
        tag += f"_az{int(azimuth)}"
    d = os.path.dirname(__file__)
    _save_planview(parcel, window, wells, os.path.join(d, f"planview_{tag}.png"), title)
    _save_gunbarrel(wells, os.path.join(d, f"gunbarrel_{tag}.png"), f"{title} — gun-barrel")
    if geojson:
        _save_geojson(parcel, window, wells, os.path.join(d, f"scenario_{tag}.geojson"))
    if save:
        _save_scenario(parcel, p, wells, asdict(feas), label)


if __name__ == "__main__":
    main()
