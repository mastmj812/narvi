"""Narvi data contract (§5): the inventory-well record + scenario params.

One InventoryWell feeds both forecasters and both visuals. This is the
single-lateral subset (slice 1); U-turn fields (leg_A/leg_B/turn_arc,
drilled vs completed divergence) and the warehouse/forecast linkage columns
get added as later slices land.

Geometry is carried in the planar WORK CRS (UTM 13N, metres) for length math,
plus WGS84 lon/lat for the frontend. Lengths surfaced to humans are in FEET.
"""

from __future__ import annotations

from dataclasses import dataclass

FT_PER_M = 3.280839895


@dataclass
class ScenarioParams:
    """Inputs for one generation run. TVD + azimuth are parameters for now;
    Phase 4 sources TVD from curated.wells and azimuth from the RRC section grid."""

    formation: str            # formation_blueox code (e.g. WCA_1)
    target_tvd_ft: float      # landing TVD
    spacing_ft: float         # leg-to-leg spacing
    setback_ft: float         # uniform boundary setback (slice 1; asymmetric later)
    # lateral azimuth (compass deg cw from N). None => auto from the parcel's
    # long axis (dominant_azimuth) as a stand-in for the RRC section grid.
    azimuth_deg: float | None = None
    min_lateral_ft: float = 4000.0
    scenario_id: str = "s1"
    deal_id: str = "demo"


@dataclass
class InventoryWell:
    scenario_id: str
    deal_id: str
    well_name: str
    well_type: str               # 'single' (slice 1) | 'uturn'
    formation: str               # formation_blueox code
    target_tvd_ft: float
    lateral_azimuth_deg: float
    # endpoints in the work CRS (UTM 13N, m) and WGS84 (lon, lat)
    heel_xy: tuple[float, float]
    toe_xy: tuple[float, float]
    heel_lonlat: tuple[float, float]
    toe_lonlat: tuple[float, float]
    completed_lateral_ft: float  # producing length (legs only)
    drilled_lateral_ft: float    # legs + turn arc (== completed for single)
    gunbarrel_x_ft: float        # cross-section offset, perpendicular to azimuth
    nearest_neighbor_spacing_ft: float
    setback_ft: float


@dataclass
class Feasibility:
    """Feasibility response — report the max that fits, never fail silently."""

    requested: int | None        # target count if the objective asked for one
    placed: int
    total_completed_ft: float
    note: str = ""
