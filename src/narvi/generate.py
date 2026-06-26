"""Scenario generation: parcel + params -> inventory wells + feasibility.

Slice 1: single laterals, uniform setback, one formation/zone, max-count
placement. Returns the wells, the drillable window (for viz), and a feasibility
report.
"""

from __future__ import annotations

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

from .parcel import WORK_EPSG
from .placement import FT_PER_M, drillable_window, place_single_laterals
from .records import Feasibility, InventoryWell, ScenarioParams

_to_wgs = Transformer.from_crs(
    CRS.from_epsg(WORK_EPSG), CRS.from_epsg(4326), always_xy=True
).transform


def generate_scenario(
    parcel: BaseGeometry, p: ScenarioParams
) -> tuple[list[InventoryWell], BaseGeometry, Feasibility]:
    window = drillable_window(parcel, p.setback_ft)
    placed = place_single_laterals(window, p.azimuth_deg, p.spacing_ft, p.min_lateral_ft)

    wells: list[InventoryWell] = []
    for i, (seg, gbx) in enumerate(placed):
        heel = (seg.coords[0][0], seg.coords[0][1])
        toe = (seg.coords[-1][0], seg.coords[-1][1])
        completed_ft = seg.length * FT_PER_M
        wells.append(
            InventoryWell(
                scenario_id=p.scenario_id,
                deal_id=p.deal_id,
                well_name=f"{p.formation}-{i + 1:02d}",
                well_type="single",
                formation=p.formation,
                target_tvd_ft=p.target_tvd_ft,
                lateral_azimuth_deg=p.azimuth_deg,
                heel_xy=heel,
                toe_xy=toe,
                heel_lonlat=tuple(round(c, 6) for c in _to_wgs(*heel)),
                toe_lonlat=tuple(round(c, 6) for c in _to_wgs(*toe)),
                completed_lateral_ft=round(completed_ft, 1),
                drilled_lateral_ft=round(completed_ft, 1),  # single: drilled == completed
                gunbarrel_x_ft=round(gbx, 1),
                nearest_neighbor_spacing_ft=p.spacing_ft,
                setback_ft=p.setback_ft,
            )
        )

    feas = Feasibility(
        requested=None,
        placed=len(wells),
        total_completed_ft=round(sum(w.completed_lateral_ft for w in wells), 1),
        note=(f"{len(wells)} {p.formation} single laterals at {p.spacing_ft:.0f} ft "
              f"spacing / {p.setback_ft:.0f} ft setback / {p.azimuth_deg:.0f}° azimuth"),
    )
    return wells, window, feas
