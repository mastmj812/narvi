"""Scenario generation: parcel + params -> inventory wells + feasibility.

single: each placed leg is its own well.
uturn : adjacent legs are paired into U-turns — two parallel legs joined at the
        toe by a semicircular turn of radius R = spacing/2. The turn arc is
        non-producing; it bulges past the toe but is pulled back so it stays
        inside the window. An odd leftover leg falls back to a single.
"""

from __future__ import annotations

import math
from dataclasses import replace

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

from .parcel import WORK_EPSG
from .placement import (
    FT_PER_M,
    dominant_azimuth,
    drillable_window,
    laterals_rotated,
    unrotate,
)
from .records import (
    Feasibility,
    InventoryWell,
    Leg,
    ScenarioParams,
    Turn,
    WineRackReport,
    Zone,
    ZoneResult,
)

_to_wgs = Transformer.from_crs(
    CRS.from_epsg(WORK_EPSG), CRS.from_epsg(4326), always_xy=True
).transform

_ARC_STEPS = 16


def _wgs(x: float, y: float) -> tuple[float, float]:
    lon, lat = _to_wgs(x, y)
    return (round(lon, 6), round(lat, 6))


def _r(xy: tuple[float, float]) -> tuple[float, float]:
    return (round(xy[0], 2), round(xy[1], 2))


def _make_leg(y, x0, x1, centroid, phi, y_mid) -> Leg:
    heel = unrotate(x0, y, centroid, phi)
    toe = unrotate(x1, y, centroid, phi)
    return Leg(
        heel_xy=_r(heel), toe_xy=_r(toe),
        heel_lonlat=_wgs(*heel), toe_lonlat=_wgs(*toe),
        length_ft=round((x1 - x0) * FT_PER_M, 1),
        gunbarrel_x_ft=round((y - y_mid) * FT_PER_M, 1),
    )


def _single_well(leg: Leg, p: ScenarioParams, n: int) -> InventoryWell:
    return InventoryWell(
        scenario_id=p.scenario_id, deal_id=p.deal_id,
        well_name=f"{p.formation}-{n:02d}", well_type="single",
        formation=p.formation, target_tvd_ft=p.target_tvd_ft,
        lateral_azimuth_deg=0.0,  # set by caller
        legs=[leg], turn=None,
        completed_lateral_ft=leg.length_ft, drilled_lateral_ft=leg.length_ft,
        nearest_neighbor_spacing_ft=p.spacing_ft, setback_ft=p.setback_ft,
    )


def _uturn_well(la, lb, spacing_m, centroid, phi, y_mid, p, n) -> InventoryWell | None:
    ya, x0a, x1a = la
    yb, x0b, x1b = lb
    r_m = spacing_m / 2.0
    common_toe = min(x1a, x1b) - r_m
    if common_toe <= x0a or common_toe <= x0b:
        return None  # legs too short to host the turn -> caller falls back to singles

    legA = _make_leg(ya, x0a, common_toe, centroid, phi, y_mid)
    legB = _make_leg(yb, x0b, common_toe, centroid, phi, y_mid)

    cx, cy = common_toe, (ya + yb) / 2.0
    arc = [(cx + r_m * math.cos(t), cy + r_m * math.sin(t))
           for t in (-math.pi / 2 + i * math.pi / _ARC_STEPS for i in range(_ARC_STEPS + 1))]
    arc_work = [unrotate(x, y, centroid, phi) for x, y in arc]
    radius_ft = r_m * FT_PER_M
    arc_ft = math.pi * radius_ft
    turn = Turn(
        arc_xy=[_r(pt) for pt in arc_work],
        arc_lonlat=[_wgs(*pt) for pt in arc_work],
        radius_ft=round(radius_ft, 1), arc_ft=round(arc_ft, 1),
        dls_deg_per_100ft=round(5729.58 / radius_ft, 2),
    )
    completed = legA.length_ft + legB.length_ft
    return InventoryWell(
        scenario_id=p.scenario_id, deal_id=p.deal_id,
        well_name=f"{p.formation}-{n:02d}", well_type="uturn",
        formation=p.formation, target_tvd_ft=p.target_tvd_ft,
        lateral_azimuth_deg=0.0,
        legs=[legA, legB], turn=turn,
        completed_lateral_ft=round(completed, 1),
        drilled_lateral_ft=round(completed + arc_ft, 1),
        nearest_neighbor_spacing_ft=p.spacing_ft, setback_ft=p.setback_ft,
    )


def generate_scenario(
    parcel: BaseGeometry, p: ScenarioParams, row_offset_ft: float = 0.0
) -> tuple[list[InventoryWell], BaseGeometry, Feasibility]:
    az = p.azimuth_deg if p.azimuth_deg is not None else dominant_azimuth(parcel)
    auto = p.azimuth_deg is None
    window = drillable_window(parcel, p.setback_ft)
    legs, centroid, phi, y_mid = laterals_rotated(
        window, az, p.spacing_ft, p.min_lateral_ft, row_offset_ft)
    spacing_m = p.spacing_ft / FT_PER_M

    # U-turn leg-to-leg = the leg spacing here; a turn tighter than the floor is
    # undrillable, so fall back to single laterals.
    uturn = p.well_type == "uturn" and p.spacing_ft >= p.uturn_min_leg_to_leg_ft
    floored = p.well_type == "uturn" and not uturn

    wells: list[InventoryWell] = []
    if uturn:
        i = 0
        while i < len(legs):
            if i + 1 < len(legs):
                w = _uturn_well(legs[i], legs[i + 1], spacing_m, centroid, phi, y_mid,
                                p, len(wells) + 1)
                if w is not None:
                    wells.append(w)
                    i += 2
                    continue
            wells.append(_single_well(_make_leg(*legs[i], centroid, phi, y_mid),
                                      p, len(wells) + 1))
            i += 1
    else:
        for leg in legs:
            wells.append(_single_well(_make_leg(*leg, centroid, phi, y_mid),
                                      p, len(wells) + 1))

    for w in wells:
        w.lateral_azimuth_deg = round(az, 1)

    n_legs = sum(len(w.legs) for w in wells)
    feas = Feasibility(
        requested=None, placed=len(wells), legs=n_legs,
        total_completed_ft=round(sum(w.completed_lateral_ft for w in wells), 1),
        total_drilled_ft=round(sum(w.drilled_lateral_ft for w in wells), 1),
        note=(f"{len(wells)} {'uturn' if uturn else 'single'} wells / {n_legs} legs of "
              f"{p.formation} at {p.spacing_ft:.0f} ft spacing / {p.setback_ft:.0f} ft setback / "
              f"{az:.1f}° azimuth{' (auto)' if auto else ''}"
              + (f"  [U-turn leg-to-leg {p.spacing_ft:.0f} < {p.uturn_min_leg_to_leg_ft:.0f} ft "
                 f"floor -> singles]" if floored else "")),
    )
    return wells, window, feas


def _interzone_offset_ft(stagger_ft, spacing_ft, d_tvd_ft, off_a, off_b) -> float:
    """3-D distance between the nearest legs of two adjacent zones: the wine-rack
    diagonal sqrt(horizontal^2 + dTVD^2). Horizontal = the row-phase difference
    folded into [0, spacing/2]."""
    phase = abs(off_a - off_b) % spacing_ft
    horiz = min(phase, spacing_ft - phase)
    return math.hypot(horiz, d_tvd_ft)


def generate_wine_rack(
    parcel: BaseGeometry,
    base: ScenarioParams,
    zones: list[Zone],
    stagger_ft: float | None = None,
    min_interzone_offset_ft: float = 300.0,
) -> tuple[list[InventoryWell], BaseGeometry, WineRackReport]:
    """Stack benches into a wine-rack: each zone placed at its TVD, adjacent zones
    phase-shifted by `stagger_ft` (default spacing/2). Vertical separation between
    zones = the difference in their (median) landing TVDs."""
    stagger = base.spacing_ft / 2.0 if stagger_ft is None else stagger_ft
    zs = sorted(zones, key=lambda z: z.target_tvd_ft)  # shallow -> deep

    all_wells: list[InventoryWell] = []
    zresults: list[ZoneResult] = []
    offsets: list[float] = []
    window: BaseGeometry | None = None
    for i, z in enumerate(zs):
        off = (i % 2) * stagger                       # alternate by depth
        offsets.append(off)
        p = replace(base, formation=z.formation, target_tvd_ft=z.target_tvd_ft)
        wells, window, feas = generate_scenario(parcel, p, row_offset_ft=off)
        all_wells.extend(wells)
        zresults.append(ZoneResult(z.formation, z.target_tvd_ft, off, len(wells), feas.legs))

    min_off = float("inf")
    for i in range(len(zs) - 1):
        d_tvd = abs(zs[i].target_tvd_ft - zs[i + 1].target_tvd_ft)
        min_off = min(min_off, _interzone_offset_ft(stagger, base.spacing_ft, d_tvd,
                                                    offsets[i], offsets[i + 1]))
    finite = min_off != float("inf")
    ok = (not finite) or min_off >= min_interzone_offset_ft

    total_wells = sum(z.wells for z in zresults)
    total_legs = sum(z.legs for z in zresults)
    report = WineRackReport(
        zones=zresults, total_wells=total_wells, total_legs=total_legs,
        total_completed_ft=round(sum(w.completed_lateral_ft for w in all_wells), 1),
        stagger_ft=stagger,
        min_interzone_offset_ft=round(min_off, 1) if finite else None,
        min_interzone_offset_ok=ok,
        note=(f"{len(zs)} zones / {total_wells} wells / {total_legs} legs; stagger "
              f"{stagger:.0f} ft; min inter-zone offset "
              f"{('%.0f ft' % min_off) if finite else 'n/a'}"
              + ("" if ok else f"  [< {min_interzone_offset_ft:.0f} ft -> frac-hit risk]")),
    )
    return all_wells, window, report
