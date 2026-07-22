"""Scenario generation: parcel + params -> inventory wells + feasibility.

single: each placed leg is its own well.
uturn : adjacent legs are paired into U-turns — two parallel legs joined at the
        toe by a semicircular turn of radius R = spacing/2. The turn arc is
        non-producing; it bulges past the toe but is pulled back so it stays
        inside the window. Pairing is chosen by a DP that maximises compliant
        (>= min_lateral) footage and may skip a leg; an unpaired leg falls back
        to a single. See _place_uturns.
"""

from __future__ import annotations

import math
from dataclasses import replace

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

from .parcel import WORK_EPSG
from .placement import (
    FT_PER_M,
    anchor_edge_azimuth,
    dominant_azimuth,
    drillable_window,
    gunbarrel_offset_ft,
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


def _make_leg(y, x0, x1, centroid, phi, gb) -> Leg:
    """gb = (azimuth_deg, origin_xy): the canonical cross-section frame — offsets
    project the work-CRS leg midpoint onto placement.cross_axis(az) from the
    parcel centroid, the SAME formula the warehouse pass-through uses, so
    generated and existing wells overlay in one gun-barrel."""
    az_deg, origin = gb
    heel = unrotate(x0, y, centroid, phi)
    toe = unrotate(x1, y, centroid, phi)
    mid = ((heel[0] + toe[0]) / 2.0, (heel[1] + toe[1]) / 2.0)
    return Leg(
        heel_xy=_r(heel), toe_xy=_r(toe),
        heel_lonlat=_wgs(*heel), toe_lonlat=_wgs(*toe),
        length_ft=round((x1 - x0) * FT_PER_M, 1),
        gunbarrel_x_ft=round(gunbarrel_offset_ft(mid, az_deg, origin), 1),
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


def _uturn_well(la, lb, spacing_m, centroid, phi, gb, p, n,
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
        legA = _make_leg(ya, x0a, common, centroid, phi, gb)
        legB = _make_leg(yb, x0b, common, centroid, phi, gb)
        arc_sign = 1.0                            # bulge past the toes (+x)
    else:
        common = max(x0a, x0b) + r_m              # turn at the heel (low-x) end
        if common >= x1a or common >= x1b:
            return None
        legA = _make_leg(ya, common, x1a, centroid, phi, gb)
        legB = _make_leg(yb, common, x1b, centroid, phi, gb)
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


def _place_uturns(legs, spacing_m, centroid, phi, gb, p, turn_at_high,
                  anchored_first: bool = False) -> list[InventoryWell]:
    """Pair legs into U-turns to MAXIMISE total compliant (>= min_lateral) completed
    footage, via a left-to-right DP that may SKIP a leg (leave it unpaired) when
    pairing it would orphan a more valuable neighbour. A U-turn joins ADJACENT legs
    only (a pair is always consecutive rows one spacing apart), so the choice is a
    1-D interval problem: at each leg, pair it with the next or leave it. An unpaired
    leg falls back to a single (filtered by the caller's min-lateral cut).

    Replaces greedy adjacent pairing — which commits to (0,1)(2,3)... and can bury a
    profitable asymmetric straddle behind an early sub-minimum pair (e.g. a notch
    corner: greedy pairs the two short rows together and drops them, where skipping
    one lets a full row carry the short one over the floor). Ties prefer pairing, so
    on a regular unit the DP reproduces the greedy layout (trailing leftover single).

    anchored_first: the caller ordered legs from a STIPULATED lease-line anchor. The
    anchored flush pair is then forced whenever it is compliant — the anchor is a
    design stipulation, and a raw-footage DP would happily skip the flush row for a
    few extra feet on a slightly-tapering unit (theCan_44: the east-anchored row was
    the shortest, so the DP orphaned it and the min-lateral cut deleted it). A
    sub-minimum anchored pair (notch corner) still falls through to the free DP."""
    n = len(legs)
    singles = [_single_well(_make_leg(*legs[i], centroid, phi, gb), p, i + 1) for i in range(n)]
    pairs: list[InventoryWell | None] = [
        _uturn_well(legs[i], legs[i + 1], spacing_m, centroid, phi, gb, p, i + 1, turn_at_high)
        if i + 1 < n else None
        for i in range(n)
    ]

    def pair_value(i: int) -> float:
        w = pairs[i]
        return w.completed_lateral_ft if w is not None and w.completed_lateral_ft >= p.min_lateral_ft else 0.0

    # best[i] = max compliant U-turn footage from legs[i:]; take[i] = pair leg i with
    # i+1 (else leave it unpaired). Ties (>=) prefer pairing.
    best = [0.0] * (n + 2)
    take = [False] * (n + 1)
    for i in range(n - 1, -1, -1):
        skip_v = best[i + 1]                        # leg i unpaired
        if pairs[i] is not None and pair_value(i) + best[i + 2] >= skip_v:
            best[i], take[i] = pair_value(i) + best[i + 2], True
        else:
            best[i], take[i] = skip_v, False

    wells: list[InventoryWell] = []
    i = 0
    # best/take are suffix-optimal (computed right-to-left), so forcing the anchored
    # flush pair and resuming the traversal at leg 2 stays optimal for the rest.
    if anchored_first and n > 1 and pairs[0] is not None and pair_value(0) > 0:
        wells.append(pairs[0])
        i = 2
    while i < n:
        if take[i]:
            wells.append(pairs[i])  # type: ignore[arg-type]
            i += 2
        else:
            wells.append(singles[i])
            i += 1
    for k, w in enumerate(wells, 1):
        w.well_name = f"{p.formation}-{k:02d}"
    return wells


def _drill_to_high(drill_from: str, az: float) -> bool:
    """Map a 'north'/'south' surface side to turn_at_high, given the azimuth: the
    turn goes at the end OPPOSITE the heels/pad. Whether the high-x end points north
    or south depends on the bearing's N-S component (cos az)."""
    north_is_high = (az % 180.0) < 90.0          # +x has a northward component
    # heels (pad) on the chosen side -> turn at the other end
    return north_is_high if drill_from == "south" else (not north_is_high)


def _deal_uturn_orientation(window: BaseGeometry, az: float, p: ScenarioParams, gb,
                            anchor: str = "center") -> bool:
    """Pick ONE turn end for the whole deal (all wells drilled from one surface
    side): place U-turns both ways on the window and return turn_at_high for the
    orientation that drills more total completed footage."""
    legs, centroid, phi, _ = laterals_rotated(window, az, p.spacing_ft, p.spacing_ft, 0.0, anchor)
    spacing_m = p.spacing_ft / FT_PER_M

    def kept_ft(turn_at_high: bool) -> float:
        return sum(w.completed_lateral_ft
                   for w in _place_uturns(legs, spacing_m, centroid, phi, gb, p, turn_at_high)
                   if w.completed_lateral_ft >= p.min_lateral_ft)

    return kept_ft(True) >= kept_ft(False)


def _place_for_anchor(window, az, p, row_offset_ft, anchor, uturn, spacing_m, gb):
    """Place wells for one anchor; returns (wells, dropped). U-turns try both turn
    ends (unless fixed) and keep the better."""
    if uturn:
        u_legs, centroid, phi, _ = laterals_rotated(
            window, az, p.spacing_ft, p.spacing_ft, row_offset_ft, anchor)
        if anchor in ("west", "east") and len(u_legs) > 1:
            # Pair from the ANCHORED end: the DP's tie-leftover single lands at the
            # end of the list, so on a uniform unit an odd row count would otherwise
            # orphan the anchored flush leg whenever that lease line falls at high-y
            # in the rotated frame — and the min-lateral cut then deletes exactly the
            # leg the user anchored (theCan_44: east-anchored 990 ft rows kept a
            # west-hugging pattern). Leftovers belong on the un-anchored side.
            xm = (min(l[1] for l in u_legs) + max(l[2] for l in u_legs)) / 2.0
            e_lo = unrotate(xm, u_legs[0][0], centroid, phi)[0]
            e_hi = unrotate(xm, u_legs[-1][0], centroid, phi)[0]
            if ((e_lo <= e_hi) and anchor == "east") or ((e_lo > e_hi) and anchor == "west"):
                u_legs = u_legs[::-1]
        anchored = anchor in ("west", "east")
        turn = p.turn_at_high
        if turn is None and p.drill_from in ("north", "south"):
            turn = _drill_to_high(p.drill_from, az)
        if turn is None:
            cands = [_place_uturns(u_legs, spacing_m, centroid, phi, gb, p, e, anchored)
                     for e in (True, False)]
            placed = max(cands, key=lambda ws: round(
                sum(w.completed_lateral_ft for w in ws if w.completed_lateral_ft >= p.min_lateral_ft), 1))
        else:
            placed = _place_uturns(u_legs, spacing_m, centroid, phi, gb, p, turn, anchored)
        wells = [w for w in placed if w.completed_lateral_ft >= p.min_lateral_ft]
        for k, w in enumerate(wells, 1):
            w.well_name = f"{p.formation}-{k:02d}"
        return wells, len(placed) - len(wells)
    legs, centroid, phi, _ = laterals_rotated(
        window, az, p.spacing_ft, p.min_lateral_ft, row_offset_ft, anchor)
    wells = [_single_well(_make_leg(*leg, centroid, phi, gb), p, k + 1)
             for k, leg in enumerate(legs)]
    return wells, _dropped_short(window, az, p, row_offset_ft, anchor)


def _deal_anchor(window, az, p, uturn, spacing_m, gb) -> str:
    """Pick where the rows hang for the whole deal: the anchor that drills the most
    completed footage (center on a tie, so a regular unit stays centered)."""
    best_a, best_ft = "center", -1.0
    for a in ("center", "west", "east"):
        ws, _ = _place_for_anchor(window, az, p, 0.0, a, uturn, spacing_m, gb)
        ft = sum(w.completed_lateral_ft for w in ws)
        if ft > best_ft + 1.0:                  # center first -> wins ties
            best_a, best_ft = a, ft
    return best_a


def _deal_anchor_zones(window, az, base, zs, z_spacings, gb) -> str:
    """Wine-rack deal anchor: evaluate each anchor on the ZONES AS THEY WILL PLACE
    — each zone's own spacing, U-turn eligibility, and stagger phase — and keep the
    anchor drilling the most total footage (center on a tie). Evaluating only the
    lead spacing at phase 0 (what `_deal_anchor` does) misses that a staggered
    phase can need the slack an edge anchor provides: on a tight cross-window the
    centered phase-0 row plateaus at one leg while a lease-line anchor fits a full
    staggered U-turn in EVERY zone (Castaway half-sections, 1,200 ft leg-to-leg in
    a 1,980 ft window)."""
    best_a, best_ft = "center", -1.0
    for a in ("center", "west", "east"):
        ft = 0.0
        for i, (z, sp) in enumerate(zip(zs, z_spacings)):
            off = (i % 2) * (sp / 2.0)                  # the placement loop's stagger
            u = base.well_type == "uturn" and sp >= base.uturn_min_leg_to_leg_ft
            p_i = replace(base, formation=z.formation, target_tvd_ft=z.target_tvd_ft,
                          spacing_ft=sp)
            ws, _ = _place_for_anchor(window, az, p_i, off, a, u, sp / FT_PER_M, gb)
            ft += sum(w.completed_lateral_ft for w in ws)
        if ft > best_ft + 1.0:                          # center first -> wins ties
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
    # A stipulated W/E anchor line DEFINES the azimuth: laterals run parallel to that
    # lease line. This overrides any sourced/long-axis azimuth so the development
    # stays exactly parallel to the setback (no fractional-degree drift).
    if p.anchor in ("west", "east"):
        edge_az = anchor_edge_azimuth(parcel, p.anchor)
        if edge_az is not None:
            return edge_az
    if p.azimuth_deg is not None:
        return p.azimuth_deg
    if p.objective == "max_count":
        return _best_azimuth(window, p)
    return dominant_azimuth(parcel)            # max_lateral: parcel long axis


def generate_scenario(
    parcel: BaseGeometry, p: ScenarioParams, row_offset_ft: float = 0.0,
    optimize_phase: bool = True, force_azimuth: float | None = None,
) -> tuple[list[InventoryWell], BaseGeometry, Feasibility]:
    ns = p.setback_ns_ft if p.setback_ns_ft is not None else p.setback_ft
    ew = p.setback_ew_ft if p.setback_ew_ft is not None else p.setback_ft
    setback_str = f"{ns:.0f}" if abs(ns - ew) < 1e-6 else f"{ns:.0f} NS/{ew:.0f} EW"
    window = drillable_window(parcel, ns, ew)
    # force_azimuth locks the bearing (the wine-rack resolves it ONCE for the deal):
    # an internally auto-resolved 'west'/'east' anchor then only hangs the rows, it
    # does NOT re-derive the azimuth from the lease-line edge (that override is only
    # for a USER-stipulated W/E anchor, which comes through _resolve_azimuth here).
    az = (force_azimuth if force_azimuth is not None
          else _resolve_azimuth(parcel, window, p)) % 180.0   # axial: fold once
    auto = p.azimuth_deg is None
    # canonical cross-section frame: parcel centroid + folded azimuth (see _make_leg)
    gb = (az, (parcel.centroid.x, parcel.centroid.y))
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
    half = p.spacing_ft / 2.0
    wells: list[InventoryWell] = []
    dropped = 0
    best_ft = None
    for a in anchors:
        # 'center' tries both row phases (a row on the midline vs straddling it) and
        # keeps the one that packs more — anchoring a row exactly on the midline can
        # fit one fewer than the equally-centered half-shift (3 vs 4 at 1,200 ft).
        # ONLY when this call owns the phase (optimize_phase): under a wine-rack the
        # phase IS the stagger — re-choosing it per zone let every zone converge to
        # the same max-footage phase and stack benches on one cross-section.
        offs = ((row_offset_ft, row_offset_ft + half)
                if a == "center" and optimize_phase else (row_offset_ft,))
        cand, cand_dropped = max(
            (_place_for_anchor(window, az, p, o, a, uturn, spacing_m, gb) for o in offs),
            key=lambda r: round(sum(w.completed_lateral_ft for w in r[0]), 1))
        ft = sum(w.completed_lateral_ft for w in cand)
        # first candidate always lands (so a fully-filtered run still carries its
        # dropped count); after that only strictly better -> center wins ties
        if best_ft is None or ft > best_ft + 1.0:
            wells, dropped, best_ft = cand, cand_dropped, ft

    for w in wells:
        w.lateral_azimuth_deg = round(az, 1)
    n_legs = sum(len(w.legs) for w in wells)
    feas = Feasibility(
        requested=None, placed=len(wells), legs=n_legs, dropped=dropped,
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
    zs = sorted(zones, key=lambda z: z.target_tvd_ft)  # shallow -> deep
    # Effective per-zone spacing is what PLACES wells (generate_scenario receives it
    # per zone); base.spacing_ft is only the fallback for zones without their own.
    # Every deal-level decision below — the U-turn feasibility gate, the anchor and
    # turn-end optimizers, the floor note — must therefore run on the zone spacings,
    # not the deal default: gating on the default reported "-> singles" (and steered
    # the optimizers with singles) while the zones actually placed U-turns.
    z_spacings = [z.spacing_ft if z.spacing_ft else base.spacing_ft for z in zs]
    lead_spacing = z_spacings[0] if z_spacings else base.spacing_ft
    stagger = lead_spacing / 2.0 if stagger_ft is None else stagger_ft
    # resolve azimuth once so every bench shares it (and any max_count sweep runs once)
    ns = base.setback_ns_ft if base.setback_ns_ft is not None else base.setback_ft
    ew = base.setback_ew_ft if base.setback_ew_ft is not None else base.setback_ft
    window0 = drillable_window(parcel, ns, ew)
    az = _resolve_azimuth(parcel, window0, base) % 180.0
    gb = (az, (parcel.centroid.x, parcel.centroid.y))
    # deal-level decisions run at the shallowest zone's spacing (a representative of
    # what actually places; zones share the resulting anchor/turn end either way)
    base_eval = replace(base, spacing_ft=lead_spacing)
    u = base.well_type == "uturn" and lead_spacing >= base.uturn_min_leg_to_leg_ft
    spacing_m = lead_spacing / FT_PER_M
    # Fix the row anchor ONCE for the deal (zones share where development hangs),
    # judged on the zones as they will actually place (spacing + stagger phase).
    if base.anchor == "auto":
        base = replace(base, anchor=_deal_anchor_zones(window0, az, base, zs, z_spacings, gb))
    # Fix ONE turn end for the deal so zones don't mix north/south turns (one surface
    # side); auto-pick the higher-footage side, evaluated at the chosen anchor.
    # 'north'/'south' -> each zone resolves the same end from drill_from + the az.
    if u and base.drill_from == "auto" and base.turn_at_high is None:
        base = replace(base, turn_at_high=_deal_uturn_orientation(
            window0, az, replace(base_eval, anchor=base.anchor), gb, base.anchor))

    all_wells: list[InventoryWell] = []
    zresults: list[ZoneResult] = []
    offsets: list[float] = []
    window: BaseGeometry | None = None
    dropped_total = 0
    for i, z in enumerate(zs):
        # per-bench spacing (Novi develops Bone Spring wider than Wolfcamp); the
        # stagger and offset follow that bench's spacing, falling back to the base.
        z_spacing = z.spacing_ft if z.spacing_ft else base.spacing_ft
        off = (i % 2) * (z_spacing / 2.0)             # alternate by depth
        offsets.append(off)
        p = replace(base, formation=z.formation, target_tvd_ft=z.target_tvd_ft,
                    spacing_ft=z_spacing, azimuth_deg=az)
        wells, window, feas = generate_scenario(
            parcel, p, row_offset_ft=off, optimize_phase=False, force_azimuth=az)
        all_wells.extend(wells)
        dropped_total += feas.dropped
        zresults.append(ZoneResult(z.formation, z.target_tvd_ft, off, len(wells), feas.legs))

    # Inter-zone offset from the ACTUAL placed laterals — center max-packing can
    # converge adjacent benches to the same cross-section, so report the real
    # nearest-leg 3-D gap (horizontal cross-section delta + dTVD), not the intended
    # stagger. A small horizontal gap is fine when dTVD separates the benches.
    zx: dict[tuple, list[float]] = {}
    for w in all_wells:
        zx.setdefault((w.formation, w.target_tvd_ft), []).extend(
            leg.gunbarrel_x_ft for leg in w.legs)
    min_off = float("inf")
    for i in range(len(zs) - 1):
        xa = zx.get((zs[i].formation, zs[i].target_tvd_ft), [])
        xb = zx.get((zs[i + 1].formation, zs[i + 1].target_tvd_ft), [])
        if not xa or not xb:
            continue
        horiz = min(abs(a - b) for a in xa for b in xb)
        d_tvd = abs(zs[i].target_tvd_ft - zs[i + 1].target_tvd_ft)
        min_off = min(min_off, math.hypot(horiz, d_tvd))
    finite = min_off != float("inf")
    ok = (not finite) or min_off >= min_interzone_offset_ft

    total_wells = sum(z.wells for z in zresults)
    total_legs = sum(z.legs for z in zresults)
    well_kind = "uturn" if any(w.turn for w in all_wells) else "single"
    # flag the floor per ZONE, at the spacing that placed that zone's wells
    floored_zs = [f"{z.formation} {sp:.0f}" for z, sp in zip(zs, z_spacings)
                  if base.well_type == "uturn" and sp < base.uturn_min_leg_to_leg_ft]
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
              + (f"  [U-turn leg-to-leg < {base.uturn_min_leg_to_leg_ft:.0f} ft floor -> "
                 f"singles: {', '.join(floored_zs)}]" if floored_zs else "")
              + (f"  [{dropped_total} short well{'s' if dropped_total != 1 else ''} "
                 f"< {base.min_lateral_ft:.0f} ft min lateral dropped]" if dropped_total else "")),
    )
    return all_wells, window, report
