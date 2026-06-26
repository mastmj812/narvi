"""Slice-1 demo: generate single laterals on a parcel + render a plan-view PNG.

    python demo.py                          # synthetic 1-mile section
    python demo.py deal.zip                 # a single-parcel shapefile (dissolved)
    python demo.py deals.zip "hecker"       # one named parcel from a multi-deal bundle
    python demo.py deals.zip "hecker" 80    # ...with an explicit azimuth (else auto)
    python demo.py deals.zip "hecker" uturn # ...as U-turn wells (else single)
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
    generate_scenario,
    load_named_parcels,
    load_parcel_zip,
    synthetic_section,
)


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


def main() -> None:
    args = list(sys.argv[1:])
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

    p = ScenarioParams(
        formation="WCA_1", target_tvd_ft=11500, azimuth_deg=azimuth, well_type=well_type,
        spacing_ft=880, setback_ft=200, min_lateral_ft=4000,
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
