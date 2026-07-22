"""Parcel feasibility + configuration scan (pure geometry, no DB).

Odd parcels — half-sections, laterally-clipped tracts, anything that isn't a
standard DSU — silently defeat the generator's defaults: the sourced grid
azimuth can cap rows below the min lateral and every candidate drops. These
helpers make that visible BEFORE the trial-and-error loop:

  * `direction_feasibility` — for one bearing, the longest straight row the
    drillable window holds and the cross-axis extent (how much room rows have
    to hang), i.e. "cross-grid rows max ~1,980 ft < 4,000 ft min lateral".
  * `scan_configs` — sweep azimuth x well-type x spacing through the actual
    placement engine and rank by completed footage; the UI adopts a row.

Everything runs on `generate_scenario`'s own placement primitives, so a scan
row IS what the generator will produce for those params — no approximations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from shapely.affinity import rotate
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from .generate import generate_scenario
from .placement import (
    FT_PER_M,
    _longest_segment,
    dominant_azimuth,
    drillable_window,
)
from .records import ScenarioParams

# row-scan pitch for the max-chord search: fine enough to catch a narrow neck,
# coarse enough to stay sub-millisecond on a section-scale window
_CHORD_SCAN_FT = 50.0


@dataclass
class DirectionFeasibility:
    """What one lateral bearing can hold in a parcel's drillable window."""

    label: str                 # 'grid' | 'long-axis' | custom
    azimuth_deg: float
    max_lateral_ft: float      # longest straight row anywhere in the window
    cross_extent_ft: float     # span across the rows (how much room to hang them)
    note: str = ""


def direction_feasibility(
    parcel: BaseGeometry,
    azimuth_deg: float,
    setback_ns_ft: float,
    setback_ew_ft: float | None = None,
    label: str = "",
    min_lateral_ft: float | None = None,
) -> DirectionFeasibility:
    """Longest straight row + cross extent for laterals along `azimuth_deg`,
    inside the setback window. `min_lateral_ft` only flavors the note."""
    window = drillable_window(parcel, setback_ns_ft, setback_ew_ft)
    az = azimuth_deg % 180.0
    if window.is_empty:
        return DirectionFeasibility(label, round(az, 1), 0.0, 0.0,
                                    note="setbacks consume the whole parcel")
    phi = 90.0 - az
    rot = rotate(window, -phi, origin=window.centroid, use_radians=False)
    minx, miny, maxx, maxy = rot.bounds
    step = _CHORD_SCAN_FT / FT_PER_M
    n = max(2, int((maxy - miny) / step))
    best = 0.0
    for i in range(n + 1):
        y = miny + (maxy - miny) * i / n
        seg = _longest_segment(
            LineString([(minx - 10.0, y), (maxx + 10.0, y)]).intersection(rot))
        if seg is not None:
            best = max(best, seg.length)
    max_lat = best * FT_PER_M
    cross = (maxy - miny) * FT_PER_M
    note = (f"{label or f'{az:.1f} deg'}: rows up to {max_lat:,.0f} ft, "
            f"{cross:,.0f} ft across")
    if min_lateral_ft is not None and max_lat < min_lateral_ft:
        note += f"  [< {min_lateral_ft:,.0f} ft min lateral — singles cannot place]"
    return DirectionFeasibility(label, round(az, 1), round(max_lat, 0),
                                round(cross, 0), note)


def parcel_feasibility(
    parcel: BaseGeometry,
    setback_ns_ft: float,
    setback_ew_ft: float | None = None,
    grid_azimuth_deg: float | None = None,
    min_lateral_ft: float | None = None,
) -> list[DirectionFeasibility]:
    """Feasibility along the offset-grid bearing (when known) and the parcel's
    long axis — the two bearings a development plan realistically uses. When
    the two coincide (a grid-conforming parcel) only 'grid' is returned."""
    out: list[DirectionFeasibility] = []
    long_ax = dominant_azimuth(parcel)
    if grid_azimuth_deg is not None:
        out.append(direction_feasibility(
            parcel, grid_azimuth_deg, setback_ns_ft, setback_ew_ft,
            label="grid", min_lateral_ft=min_lateral_ft))
        # axial angular distance (0-90): folds 162.8 vs 71.3 to ~88 deg apart
        d = abs(grid_azimuth_deg - long_ax) % 180.0
        if min(d, 180.0 - d) < 10.0:
            return out                      # long axis IS the grid — one row
    out.append(direction_feasibility(
        parcel, long_ax, setback_ns_ft, setback_ew_ft,
        label="long-axis", min_lateral_ft=min_lateral_ft))
    return out


@dataclass
class ScanConfig:
    """One swept configuration, ranked by what it actually drills."""

    azimuth_label: str
    azimuth_deg: float
    well_type: str             # 'single' | 'uturn'
    spacing_ft: float
    wells: int
    legs: int
    completed_ft: float
    ft_per_well: float
    note: str


_DEFAULT_SPACINGS = (880.0, 990.0, 1200.0, 1320.0)


def scan_configs(
    parcel: BaseGeometry,
    base: ScenarioParams,
    azimuths: list[tuple[str, float]],
    spacings: tuple[float, ...] = _DEFAULT_SPACINGS,
) -> list[ScanConfig]:
    """Sweep azimuth x well-type x spacing through `generate_scenario` and rank
    by completed footage (then well count). U-turn rows under the leg-to-leg
    floor are skipped — they'd place as singles and duplicate the single rows.
    `azimuths` = [(label, bearing)], normally from `parcel_feasibility`."""
    seen_sp = []
    for sp in (*spacings, base.spacing_ft):
        if sp > 0 and sp not in seen_sp:
            seen_sp.append(sp)

    out: list[ScanConfig] = []
    for lab, az in azimuths:
        for wt in ("single", "uturn"):
            for sp in seen_sp:
                if wt == "uturn" and sp < base.uturn_min_leg_to_leg_ft:
                    continue
                p = replace(base, azimuth_deg=az, well_type=wt, spacing_ft=sp)
                wells, _, feas = generate_scenario(parcel, p)
                if wt == "uturn" and not any(w.turn for w in wells):
                    continue               # placed as singles anyway -> duplicate row
                n = len(wells)
                out.append(ScanConfig(
                    azimuth_label=lab, azimuth_deg=round(az, 1), well_type=wt,
                    spacing_ft=sp, wells=n, legs=feas.legs,
                    completed_ft=feas.total_completed_ft,
                    ft_per_well=round(feas.total_completed_ft / n, 1) if n else 0.0,
                    note=feas.note))
    out.sort(key=lambda c: (-c.completed_ft, -c.wells, c.spacing_ft))
    return out


def axial_delta_deg(a: float, b: float) -> float:
    """Angular distance between two axial bearings, folded to [0, 90]."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def zero_well_hint(
    parcel: BaseGeometry,
    p: ScenarioParams,
    used_azimuth_deg: float,
) -> str:
    """Why a run placed nothing, and what direction would work — appended to the
    generator note so a zero isn't a dead end. Pure geometry: max straight row
    at the used bearing (plus the U-turn completed ceiling, turn trim included)
    vs the parcel's long axis."""
    ns = p.setback_ns_ft if p.setback_ns_ft is not None else p.setback_ft
    ew = p.setback_ew_ft if p.setback_ew_ft is not None else p.setback_ft
    used = direction_feasibility(parcel, used_azimuth_deg, ns, ew)
    parts: list[str] = []
    if p.well_type == "uturn":
        # both legs trimmed by the turn radius at the common end
        ceiling = max(0.0, 2.0 * (used.max_lateral_ft - p.spacing_ft / 2.0))
        parts.append(f"rows along {used.azimuth_deg:.0f}° max {used.max_lateral_ft:,.0f} ft "
                     f"(U-turn completes ≤ {ceiling:,.0f} ft)")
    else:
        parts.append(f"rows along {used.azimuth_deg:.0f}° max {used.max_lateral_ft:,.0f} ft")
    long_ax = dominant_azimuth(parcel)
    if axial_delta_deg(long_ax, used_azimuth_deg) >= 10.0:
        alt = direction_feasibility(parcel, long_ax, ns, ew)
        parts.append(f"long axis {alt.azimuth_deg:.0f}° fits rows up to "
                     f"{alt.max_lateral_ft:,.0f} ft — try the azimuth override")
    return "  [no wells: " + "; ".join(parts) + "]"
