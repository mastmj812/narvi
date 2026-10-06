"""PDP standoff (frac-hit) check: how close does each planned lateral land to an
existing producer, in 3-D?

The wine-rack's min_interzone_offset only compares GENERATED benches with each
other; a planned stick stacked on top of a producing parent (Vault S2: a WCA_1
at 11,800' ~230 ft above the University 45 20 1H WCB_1) slipped through. This
module measures, per planned leg, the nearest PDP lateral it actually runs
alongside:

- Pairing is co-extent OVERLAP along the planned leg's axis (>= 30% of the
  shorter projected length — the narvi in-unit membership fraction), never
  bare min-distance: a toe-to-heel neighbour in the next unit isn't a frac-hit
  geometry.
- Horizontal gap = plan-view distance between the planned leg and the PDP leg
  clipped to the overlapped stretch (handles non-parallel parents: the
  closest approach over the shared stretch, not the midpoint offset).
- 3-D gap = hypot(horizontal, |dTVD|), TVDs from the landing medians/as-built.

Warning only (soft, like the inter-zone flag): it annotates wells and returns
notes; it never moves or drops anything. Pure — no DB; the backend supplies
the PDP wells (warehouse.inventory_from_warehouse, category 'pdp')."""

from __future__ import annotations

import math

from shapely.geometry import LineString

from .placement import FT_PER_M
from .records import InventoryWell

# Default flag distance (3-D, ft). Half a typical 1,320 ft leg-to-leg: a planned
# leg inside it sits in the parent's half-spacing. Matches the 660 ft dev-scenario
# parent-offset gate in spirit (sql/50) but is NOT coupled to it.
DEFAULT_PDP_STANDOFF_FT = 660.0
# co-extent pairing fraction (same as the in-unit membership rule)
PDP_OVERLAP_FRAC = 0.30


def _overlap_gap_m(a, b, c, d, min_frac: float) -> float | None:
    """Plan-view gap (m) between planned leg a->b and PDP leg c->d over their
    co-extent stretch along a->b, or None when they don't run alongside."""
    ax, ay = a
    L = math.hypot(b[0] - ax, b[1] - ay)
    if L <= 0:
        return None
    ux, uy = (b[0] - ax) / L, (b[1] - ay) / L
    tc = (c[0] - ax) * ux + (c[1] - ay) * uy
    td = (d[0] - ax) * ux + (d[1] - ay) * uy
    if abs(td - tc) < 1e-6:
        return None                                  # PDP perpendicular: no co-extent
    lo, hi = max(min(tc, td), 0.0), min(max(tc, td), L)
    shorter = min(L, abs(td - tc))
    if hi - lo <= 0 or (hi - lo) / shorter < min_frac:
        return None

    def at(t: float) -> tuple[float, float]:         # point on c->d projecting to t
        s = (t - tc) / (td - tc)
        return (c[0] + s * (d[0] - c[0]), c[1] + s * (d[1] - c[1]))

    return LineString([a, b]).distance(LineString([at(lo), at(hi)]))


def apply_pdp_standoff(
    planned: list[InventoryWell],
    pdp: list[InventoryWell],
    min_gap_ft: float = DEFAULT_PDP_STANDOFF_FT,
    min_overlap_frac: float = PDP_OVERLAP_FRAC,
) -> list[str]:
    """Annotate each planned well with its nearest co-extent PDP (pdp_gap_* fields,
    in place) and return one note per well closer than `min_gap_ft` (3-D).
    PDP wells without a TVD are skipped (no vertical term to judge)."""
    parents = [p for p in pdp if p.target_tvd_ft and p.target_tvd_ft > 0]
    notes: list[str] = []
    for w in planned:
        best: tuple[float, float, float, InventoryWell] | None = None
        for leg in w.legs:
            for p in parents:
                for pl in p.legs:
                    h = _overlap_gap_m(leg.heel_xy, leg.toe_xy, pl.heel_xy, pl.toe_xy,
                                       min_overlap_frac)
                    if h is None:
                        continue
                    horiz = h * FT_PER_M
                    dtvd = abs(w.target_tvd_ft - p.target_tvd_ft)
                    gap = math.hypot(horiz, dtvd)
                    if best is None or gap < best[0]:
                        best = (gap, horiz, dtvd, p)
        if best is None:
            w.pdp_gap_ft = w.pdp_gap_horiz_ft = w.pdp_gap_dtvd_ft = None
            w.pdp_gap_well = None
            continue
        gap, horiz, dtvd, p = best
        w.pdp_gap_ft, w.pdp_gap_horiz_ft, w.pdp_gap_dtvd_ft = (
            round(gap, 1), round(horiz, 1), round(dtvd, 1))
        w.pdp_gap_well = p.well_name
        if gap < min_gap_ft:
            notes.append(
                f"PDP standoff: {w.well_name} is {gap:,.0f} ft from PDP {p.well_name} "
                f"({p.formation} {p.target_tvd_ft:,.0f} ft TVD; {horiz:,.0f} ft across, "
                f"{dtvd:,.0f} ft vertical) < {min_gap_ft:,.0f} ft -> frac-hit risk")
    return notes
