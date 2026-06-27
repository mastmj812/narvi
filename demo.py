"""Slice-1 demo: generate single laterals on a parcel + render a plan-view PNG.

    python demo.py                          # synthetic 1-mile section
    python demo.py deal.zip                 # a single-parcel shapefile (dissolved)
    python demo.py deals.zip "hecker"       # one named parcel from a multi-deal bundle
    python demo.py deals.zip "hecker" 80    # ...with an explicit azimuth (else auto)
    python demo.py deals.zip "hecker" uturn # ...as U-turn wells (else single)
    python demo.py winerack uturn           # multi-zone wine-rack + gun-barrel cross-section
    python demo.py deals.zip "hecker" winerack warehouse  # zones from the warehouse (real TVDs)
    python demo.py deals.zip                # list the deal names in a bundle

Tweak the ScenarioParams below to explore spacing / azimuth / setback.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import MultiPolygon

from narvi import (
    ScenarioParams,
    Zone,
    generate_scenario,
    generate_wine_rack,
    load_named_parcels,
    load_parcel_zip,
    synthetic_section,
)

# A placeholder Delaware bench stack for the wine-rack demo (TVDs are parameters
# unless `warehouse` mode is on, which sources median landing TVD per
# formation_blueox from curated.wells_enriched in the AOI).
_DEMO_ZONES = [Zone("AVA_2", 9500), Zone("BS2_S", 10500), Zone("WCA_1", 11500), Zone("WCA_2", 11700)]
# benches requested when sourcing zones from the warehouse (shallow -> deep Delaware)
_WAREHOUSE_STACK = ["AVA_0", "BS2_S", "BS3_C", "WCXY", "WCA_1", "WCA_2", "WCB_1", "WCC"]
_PALETTE = ["#f97316", "#2563eb", "#10b981", "#a855f7", "#dc2626", "#0891b2", "#eab308", "#db2777"]


def _plot(parcel, window, wells, path: str, label: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 8))

    def ring(geom, **kw):
        polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
        for poly in polys:
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, **kw)

    ring(parcel, color="#1f2937", lw=1.5, label="parcel")
    ring(window, color="#2563eb", lw=1.0, ls="--", label="drillable window")
    for w in wells:
        for leg in w.legs:  # producing legs (orange)
            ax.plot([leg.heel_xy[0], leg.toe_xy[0]], [leg.heel_xy[1], leg.toe_xy[1]],
                    color="#f97316", lw=2)
        if w.turn:  # non-producing turn arc (violet)
            ax.plot([pt[0] for pt in w.turn.arc_xy], [pt[1] for pt in w.turn.arc_xy],
                    color="#a855f7", lw=1.5)
    ax.set_aspect("equal")
    ax.set_title(f"{label} — {len(wells)} laterals (UTM 13N m)")
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    print(f"  wrote {path}")


def _plot_gunbarrel(wells, path: str, title: str) -> None:
    """Cross-section (looking down the lateral axis): each leg a dot at
    (cross-section offset, TVD), colored by bench; U-turn pairs linked by a bar;
    the inter-zone wine-rack stagger is visible as the horizontal phase shift."""
    fig, ax = plt.subplots(figsize=(9, 5.5))
    forms = sorted({w.formation for w in wells},
                   key=lambda f: min(w.target_tvd_ft for w in wells if w.formation == f))
    color = {f: _PALETTE[i % len(_PALETTE)] for i, f in enumerate(forms)}
    for w in wells:
        c = color[w.formation]
        if w.turn:  # link the two legs of a U-turn at their TVD
            xa, xb = w.legs[0].gunbarrel_x_ft, w.legs[1].gunbarrel_x_ft
            ax.plot([xa, xb], [w.target_tvd_ft, w.target_tvd_ft], color=c, lw=0.8, alpha=0.5, zorder=2)
        for leg in w.legs:
            ax.scatter(leg.gunbarrel_x_ft, w.target_tvd_ft, color=c, s=20, zorder=3)
    handles = [plt.Line2D([], [], marker="o", ls="", color=color[f], label=f) for f in forms]
    ax.legend(handles=handles, fontsize=8, loc="upper right", title="bench")
    ax.invert_yaxis()  # deeper = lower
    ax.set_xlabel("cross-section offset (ft)")
    ax.set_ylabel("TVD (ft)")
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    print(f"  wrote {path}")


def main() -> None:
    args = list(sys.argv[1:])
    winerack = "winerack" in args
    if winerack:
        args.remove("winerack")
    warehouse = "warehouse" in args
    if warehouse:
        args.remove("warehouse")
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
        if warehouse:  # source real median landing TVDs per bench from the warehouse
            from narvi.warehouse import get_connection, zones_from_warehouse
            conn = get_connection()
            try:
                zones, stats = zones_from_warehouse(
                    conn, parcel, _WAREHOUSE_STACK, buffer_ft=5280.0, split_multimodal=True)
            finally:
                conn.close()
            print("warehouse TVD sourcing:")
            for st in stats:
                print(f"  {st.note}")
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
        _plot(parcel, window, wells, os.path.join(d, f"planview_{tag}.png"), f"{label} wine-rack ({well_type})")
        _plot_gunbarrel(wells, os.path.join(d, f"gunbarrel_{tag}.png"), f"{label} wine-rack — gun-barrel")
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
    _plot(parcel, window, wells, os.path.join(os.path.dirname(__file__), f"planview_{tag}.png"), title)


if __name__ == "__main__":
    main()
