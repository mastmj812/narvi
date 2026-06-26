"""Slice-1 demo: generate single laterals on a parcel + render a plan-view PNG.

    python demo.py                 # synthetic 1-mile section
    python demo.py path/to/deal.zip   # a real deal shapefile

Tweak the ScenarioParams below to explore spacing / azimuth / setback.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import MultiPolygon

from narvi import ScenarioParams, generate_scenario, load_parcel_zip, synthetic_section


def _plot(parcel, window, wells, path: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 8))

    def ring(geom, **kw):
        polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
        for poly in polys:
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, **kw)

    ring(parcel, color="#1f2937", lw=1.5, label="parcel")
    ring(window, color="#2563eb", lw=1.0, ls="--", label="drillable window")
    for w in wells:
        ax.plot([w.heel_xy[0], w.toe_xy[0]], [w.heel_xy[1], w.toe_xy[1]],
                color="#f97316", lw=2)
    ax.set_aspect("equal")
    ax.set_title(f"{len(wells)} laterals — UTM 13N (m)")
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    print(f"  wrote {path}")


def main() -> None:
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            parcel = load_parcel_zip(f.read())
        src = sys.argv[1]
    else:
        parcel = synthetic_section()
        src = "synthetic 1-mile section"

    p = ScenarioParams(
        formation="WCA_1", target_tvd_ft=11500,  # azimuth_deg omitted -> auto from parcel
        spacing_ft=880, setback_ft=200, min_lateral_ft=4000,
    )
    wells, window, feas = generate_scenario(parcel, p)

    print(f"parcel: {src}  ({parcel.area / 4046.8564224:.0f} ac)")
    print(f"feasibility: {feas.note}")
    print(f"  placed={feas.placed}  total_completed={feas.total_completed_ft:,.0f} ft")
    for w in wells:
        print(f"  {w.well_name}  {w.completed_lateral_ft:>7,.0f} ft  "
              f"gunbarrel_x={w.gunbarrel_x_ft:>8,.0f} ft")
    _plot(parcel, window, wells, os.path.join(os.path.dirname(__file__), "demo_planview.png"))


if __name__ == "__main__":
    main()
