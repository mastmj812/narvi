"""Scenario generation: parcel + params -> inventory wells + feasibility.

single: each placed leg is its own well.
uturn : adjacent legs are paired into U-turns — two parallel legs joined at the
        toe by a semicircular turn of radius R = spacing/2. The turn arc is
        non-producing; it bulges past the toe but is pulled back so it stays
        inside the window. An odd leftover leg falls back to a single.
"""

from __future__ import annotations

import math

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
from .records import Feasibility, InventoryWell, Leg, ScenarioParams, Turn

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
    parcel: BaseGeometry, p: ScenarioParams
) -> tuple[list[InventoryWell], BaseGeometry, Feasibility]:
    az = p.azimuth_deg if p.azimuth_deg is not None else dominant_azimuth(parcel)
    auto = p.azimuth_deg is None
    window = drillable_window(parcel, p.setback_ft)
    legs, centroid, phi, y_mid = laterals_rotated(window, az, p.spacing_ft, p.min_lateral_ft)
    spacing_m = p.spacing_ft / FT_PER_M

    wells: list[InventoryWell] = []
    if p.well_type == "uturn":
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
        note=(f"{len(wells)} {p.well_type} wells / {n_legs} legs of {p.formation} at "
              f"{p.spacing_ft:.0f} ft spacing / {p.setback_ft:.0f} ft setback / "
              f"{az:.1f}° azimuth{' (auto)' if auto else ''}"),
    )
    return wells, window, feas
