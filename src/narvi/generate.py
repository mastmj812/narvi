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


def _uturn_well(la, lb, spacing_m, centroid, phi, y_mid, p, n,
                turn_at_high: bool = True) -> InventoryWell | None:
    """Pair two adjacent rows into a U-turn. The semicircular turn sits at ONE end:
    turn_at_high -> the high-x (toe) end, both legs trimmed to the shorter row's far
    boundary (symmetric-ish); turn_at_high=False -> the low-x (heel) end, each leg
    then runs to its OWN far boundary (asymmetric — captures an irregular far edge,
    e.g. a notched unit, that the symmetric turn would waste). Caller tries both and
    keeps the one that drills more."""
    ya, x0a, x1a = la
    yb, x0b, x1b = lb
    r_m = spacing_m / 2.0
    if turn_at_high:
        common = min(x1a, x1b) - r_m              # turn at the toe (high-x) end
        if common <= x0a or common <= x0b:
            return None
        legA = _make_leg(ya, x0a, common, centroid, phi, y_mid)
        legB = _make_leg(yb, x0b, common, centroid, phi, y_mid)
        arc_sign = 1.0                            # bulge past the toes (+x)
    else:
        common = max(x0a, x0b) + r_m              # turn at the heel (low-x) end
        if common >= x1a or common >= x1b:
            return None
        legA = _make_leg(ya, common, x1a, centroid, phi, y_mid)
        legB = _make_leg(yb, common, x1b, centroid, phi, y_mid)
        arc_sign = -1.0                           # bulge past the heels (-x)

    cx, cy = common, (ya + yb) / 2.0
    arc = [(cx + arc_sign * r_m * math.cos(t), cy + r_m * math.sin(t))
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


def _place_uturns(legs, spacing_m, centroid, phi, y_mid, p, turn_at_high) -> list[InventoryWell]:
    """Pair adjacent rows into U-turns at the given turn end; an unpaired/too-short
    leftover falls back to a single."""
    wells: list[InventoryWell] = []
    i = 0
    while i < len(legs):
        if i + 1 < len(legs):
            w = _uturn_well(legs[i], legs[i + 1], spacing_m, centroid, phi, y_mid,
                            p, len(wells) + 1, turn_at_high)
            if w is not None:
                wells.append(w)
                i += 2
                continue
        wells.append(_single_well(_make_leg(*legs[i], centroid, phi, y_mid), p, len(wells) + 1))
        i += 1
    return wells


def _drill_to_high(drill_from: str, az: float) -> bool:
    """Map a 'north'/'south' surface side to turn_at_high, given the azimuth: the
    turn goes at the end OPPOSITE the heels/pad. Whether the high-x end points north
    or south depends on the bearing's N-S component (cos az)."""
    north_is_high = (az % 180.0) < 90.0          # +x has a northward component
    # heels (pad) on the chosen side -> turn at the other end
    return north_is_high if drill_from == "south" else (not north_is_high)


def _deal_uturn_orientation(window: BaseGeometry, az: float, p: ScenarioParams,
                            anchor: str = "center") -> bool:
    """Pick ONE turn end for the whole deal (all wells drilled from one surface
    side): place U-turns both ways on the window and return turn_at_high for the
    orientation that drills more total completed footage."""
    legs, centroid, phi, y_mid = laterals_rotated(window, az, p.spacing_ft, p.spacing_ft, 0.0, anchor)
    spacing_m = p.spacing_ft / FT_PER_M
    hi = sum(w.completed_lateral_ft
             for w in _place_uturns(legs, spacing_m, centroid, phi, y_mid, p, True))
    lo = sum(w.completed_lateral_ft
             for w in _place_uturns(legs, spacing_m, centroid, phi, y_mid, p, False))
    return hi >= lo


def _place_for_anchor(window, az, p, row_offset_ft, anchor, uturn, spacing_m):
    """Place wells for one anchor; returns (wells, dropped). U-turns try both turn
    ends (unless fixed) and keep the better."""
    if uturn:
        u_legs, centroid, phi, y_mid = laterals_rotated(
            window, az, p.spacing_ft, p.spacing_ft, row_offset_ft, anchor)
        turn = p.turn_at_high
        if turn is None and p.drill_from in ("north", "south"):
            turn = _drill_to_high(p.drill_from, az)
        if turn is None:
            cands = [_place_uturns(u_legs, spacing_m, centroid, phi, y_mid, p, e)
                     for e in (True, False)]
            placed = max(cands, key=lambda ws: round(sum(w.completed_lateral_ft for w in ws), 1))
        else:
            placed = _place_uturns(u_legs, spacing_m, centroid, phi, y_mid, p, turn)
        wells = [w for w in placed if w.completed_lateral_ft >= p.min_lateral_ft]
        for k, w in enumerate(wells, 1):
            w.well_name = f"{p.formation}-{k:02d}"
        return wells, len(placed) - len(wells)
    legs, centroid, phi, y_mid = laterals_rotated(
        window, az, p.spacing_ft, p.min_lateral_ft, row_offset_ft, anchor)
    wells = [_single_well(_make_leg(*leg, centroid, phi, y_mid), p, k + 1)
             for k, leg in enumerate(legs)]
    return wells, _dropped_short(window, az, p, row_offset_ft, anchor)


def _deal_anchor(window, az, p, uturn, spacing_m) -> str:
    """Pick where the rows hang for the whole deal: the anchor that drills the most
    completed footage (center on a tie, so a regular unit stays centered)."""
    best_a, best_ft = "center", -1.0
    for a in ("center", "west", "east"):
        ws, _ = _place_for_anchor(window, az, p, 0.0, a, uturn, spacing_m)
        ft = sum(w.completed_lateral_ft for w in ws)
        if ft > best_ft + 1.0:                  # center first -> wins ties
            best_a, best_ft = a, ft
    return best_a


def _count_legs(window: BaseGeometry, az: float, p: ScenarioParams, offset: float,
                anchor: str = "center") -> int:
    return len(laterals_rotated(window, az, p.spacing_ft, p.min_lateral_ft, offset, anchor)[0])


def _dropped_short(window: BaseGeometry, az: float, p: ScenarioParams, offset: float,
                   anchor: str = "center") -> int:
    """Rows that would place but for the min-lateral filter — the short edge
    laterals on an irregular/tapering parcel, which is why a placement can cluster
    in the fuller middle of the unit."""
    if p.min_lateral_ft <= 0:
        return 0
    full = _count_legs(window, az, replace(p, min_lateral_ft=0.0), offset, anchor)
    return max(0, full - _count_legs(window, az, p, offset, anchor))


def _best_offset(window: BaseGeometry, az: float, p: ScenarioParams) -> float:
    """Pick the row phase (0 or spacing/2) that fits more legs (max_count)."""
    half = p.spacing_ft / 2.0
    return half if _count_legs(window, az, p, half) > _count_legs(window, az, p, 0.0) else 0.0


def _best_azimuth(window: BaseGeometry, p: ScenarioParams) -> float:
    """Sweep azimuth (5deg) x row phase for the most legs (max_count objective)."""
    best_az, best_n = 0.0, -1
    for a in range(0, 180, 5):
        n = max(_count_legs(window, float(a), p, 0.0),
                _count_legs(window, float(a), p, p.spacing_ft / 2.0))
        if n > best_n:
            best_az, best_n = float(a), n
    return best_az


def _resolve_azimuth(parcel: BaseGeometry, window: BaseGeometry, p: ScenarioParams) -> float:
    if p.azimuth_deg is not None:
        return p.azimuth_deg
    if p.objective == "max_count":
        return _best_azimuth(window, p)
    return dominant_azimuth(parcel)            # max_lateral: parcel long axis


def generate_scenario(
    parcel: BaseGeometry, p: ScenarioParams, row_offset_ft: float = 0.0,
    optimize_phase: bool = True,
) -> tuple[list[InventoryWell], BaseGeometry, Feasibility]:
    ns = p.setback_ns_ft if p.setback_ns_ft is not None else p.setback_ft
    ew = p.setback_ew_ft if p.setback_ew_ft is not None else p.setback_ft
    setback_str = f"{ns:.0f}" if abs(ns - ew) < 1e-6 else f"{ns:.0f} NS/{ew:.0f} EW"
    window = drillable_window(parcel, ns, ew)
    az = _resolve_azimuth(parcel, window, p)
    auto = p.azimuth_deg is None
    # max_count also optimizes the single-zone row phase (the wine-rack manages its
    # own stagger, so it passes optimize_phase=False).
    if optimize_phase and p.objective == "max_count" and row_offset_ft == 0.0:
        row_offset_ft = _best_offset(window, az, p)
    spacing_m = p.spacing_ft / FT_PER_M

    # U-turn leg-to-leg = the leg spacing here; a turn tighter than the floor is
    # undrillable, so fall back to single laterals.
    uturn = p.well_type == "uturn" and p.spacing_ft >= p.uturn_min_leg_to_leg_ft
    floored = p.well_type == "uturn" and not uturn

    # Where the rows HANG across the unit. 'auto' tries center/west/east and keeps
    # the one that drills the most (center on a tie, so a regular unit stays
    # centered); west/east anchor the first lateral at that section-line setback,
    # which is how development is actually laid out and which row lands in a cutout.
    anchors = ["center", "west", "east"] if p.anchor == "auto" else [p.anchor]
    wells: list[InventoryWell] = []
    dropped = 0
    best_ft = -1.0
    for a in anchors:
        cand, cand_dropped = _place_for_anchor(window, az, p, row_offset_ft, a, uturn, spacing_m)
        ft = sum(w.completed_lateral_ft for w in cand)
        if ft > best_ft + 1.0:                      # center first -> wins ties
            wells, dropped, best_ft = cand, cand_dropped, ft

    for w in wells:
        w.lateral_azimuth_deg = round(az, 1)
    n_legs = sum(len(w.legs) for w in wells)
    feas = Feasibility(
        requested=None, placed=len(wells), legs=n_legs,
        total_completed_ft=round(sum(w.completed_lateral_ft for w in wells), 1),
        total_drilled_ft=round(sum(w.drilled_lateral_ft for w in wells), 1),
        note=(f"{len(wells)} {'uturn' if uturn else 'single'} wells / {n_legs} legs of "
              f"{p.formation} at {p.spacing_ft:.0f} ft spacing / {setback_str} ft setback / "
              f"{az:.1f}° azimuth{' (auto)' if auto else ''}"
              + (f"  [U-turn leg-to-leg {p.spacing_ft:.0f} < {p.uturn_min_leg_to_leg_ft:.0f} ft "
                 f"floor -> singles]" if floored else "")
              + (f"  [{dropped} short {'well' if uturn else 'lateral'}{'s' if dropped != 1 else ''} "
                 f"< {p.min_lateral_ft:.0f} ft dropped]" if dropped else "")),
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
    # resolve azimuth once so every bench shares it (and any max_count sweep runs once)
    ns = base.setback_ns_ft if base.setback_ns_ft is not None else base.setback_ft
    ew = base.setback_ew_ft if base.setback_ew_ft is not None else base.setback_ft
    window0 = drillable_window(parcel, ns, ew)
    az = _resolve_azimuth(parcel, window0, base)
    u = base.well_type == "uturn" and base.spacing_ft >= base.uturn_min_leg_to_leg_ft
    spacing_m = base.spacing_ft / FT_PER_M
    # Fix the row anchor ONCE for the deal (zones share where development hangs).
    if base.anchor == "auto":
        base = replace(base, anchor=_deal_anchor(window0, az, base, u, spacing_m))
    # Fix ONE turn end for the deal so zones don't mix north/south turns (one surface
    # side); auto-pick the higher-footage side, evaluated at the chosen anchor.
    # 'north'/'south' -> each zone resolves the same end from drill_from + the az.
    if u and base.drill_from == "auto" and base.turn_at_high is None:
        base = replace(base, turn_at_high=_deal_uturn_orientation(window0, az, base, base.anchor))
    zs = sorted(zones, key=lambda z: z.target_tvd_ft)  # shallow -> deep

    all_wells: list[InventoryWell] = []
    zresults: list[ZoneResult] = []
    offsets: list[float] = []
    window: BaseGeometry | None = None
    for i, z in enumerate(zs):
        off = (i % 2) * stagger                       # alternate by depth
        offsets.append(off)
        p = replace(base, formation=z.formation, target_tvd_ft=z.target_tvd_ft, azimuth_deg=az)
        wells, window, feas = generate_scenario(parcel, p, row_offset_ft=off, optimize_phase=False)
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
    well_kind = "uturn" if any(w.turn for w in all_wells) else "single"
    floored = base.well_type == "uturn" and base.spacing_ft < base.uturn_min_leg_to_leg_ft
    report = WineRackReport(
        zones=zresults, total_wells=total_wells, total_legs=total_legs,
        total_completed_ft=round(sum(w.completed_lateral_ft for w in all_wells), 1),
        stagger_ft=stagger,
        min_interzone_offset_ft=round(min_off, 1) if finite else None,
        min_interzone_offset_ok=ok,
        note=(f"{len(zs)} zones / {total_wells} {well_kind} wells / {total_legs} legs; stagger "
              f"{stagger:.0f} ft; min inter-zone offset "
              f"{('%.0f ft' % min_off) if finite else 'n/a'}"
              + ("" if ok else f"  [< {min_interzone_offset_ft:.0f} ft -> frac-hit risk]")
              + (f"  [U-turn spacing {base.spacing_ft:.0f} < {base.uturn_min_leg_to_leg_ft:.0f} ft "
                 f"floor -> singles]" if floored else "")),
    )
    return all_wells, window, report
