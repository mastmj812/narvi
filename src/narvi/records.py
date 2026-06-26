"""Narvi data contract (§5): the inventory-well record + scenario params.

One InventoryWell feeds both forecasters and both visuals. A well has 1 leg
(single lateral) or 2 legs joined by a semicircular turn (U-turn). The turn arc
is NON-PRODUCING: completed_lateral_ft = sum of leg lengths (drives EUR);
drilled_lateral_ft = legs + turn arc (drives D&C cost).

Geometry is carried in the planar WORK CRS (UTM 13N, metres) plus WGS84 lon/lat
for the frontend. Lengths surfaced to humans are in FEET.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FT_PER_M = 3.280839895


@dataclass
class ScenarioParams:
    """Inputs for one generation run. TVD + azimuth are parameters for now;
    Phase 4 sources TVD from curated.wells and azimuth from the RRC section grid."""

    formation: str            # formation_blueox code (e.g. WCA_1)
    target_tvd_ft: float      # landing TVD
    spacing_ft: float         # leg-to-leg spacing (also the U-turn leg separation)
    setback_ft: float         # uniform boundary setback (slice 1; asymmetric later)
    # lateral azimuth (compass deg cw from N). None => auto from the parcel's
    # long axis (dominant_azimuth) as a stand-in for the RRC section grid.
    azimuth_deg: float | None = None
    well_type: str = "single"  # 'single' | 'uturn' (uturn pairs adjacent legs)
    # placement objective when azimuth is auto: 'max_lateral' (default) runs along
    # the parcel long axis for the longest laterals; 'max_count' sweeps azimuth +
    # row phase for the most legs. Default favors longer laterals (capital-efficient).
    objective: str = "max_lateral"
    min_lateral_ft: float = 4000.0
    # U-turn leg-to-leg floor: below this the turn radius (leg-to-leg/2) is too
    # tight to drill. 990 ft is a conservative hard floor — Novi's 214 real U-turns
    # run ~1,400-1,600 ft typical (median 1,589); ~1,500 is a realistic default.
    uturn_min_leg_to_leg_ft: float = 990.0
    # asymmetric per-boundary setbacks (override the uniform setback_ft). Geographic
    # N/S vs E/W: edges facing N/S use setback_ns_ft, edges facing E/W use setback_ew_ft.
    setback_ns_ft: float | None = None
    setback_ew_ft: float | None = None
    scenario_id: str = "s1"
    deal_id: str = "demo"


@dataclass
class Leg:
    """One producing leg (heel -> toe) in work CRS (m) + WGS84."""

    heel_xy: tuple[float, float]
    toe_xy: tuple[float, float]
    heel_lonlat: tuple[float, float]
    toe_lonlat: tuple[float, float]
    length_ft: float
    gunbarrel_x_ft: float        # cross-section offset, perpendicular to azimuth


@dataclass
class Turn:
    """The non-producing semicircular U-turn joining two legs at the toe."""

    arc_xy: list[tuple[float, float]]      # polyline, work CRS (m)
    arc_lonlat: list[tuple[float, float]]  # polyline, WGS84
    radius_ft: float
    arc_ft: float                          # pi * R
    dls_deg_per_100ft: float               # dogleg severity = 5729.58 / R(ft)


@dataclass
class InventoryWell:
    scenario_id: str
    deal_id: str
    well_name: str
    well_type: str               # 'single' | 'uturn'
    formation: str               # formation_blueox code
    target_tvd_ft: float
    lateral_azimuth_deg: float
    legs: list[Leg]              # 1 (single) or 2 (uturn)
    turn: Turn | None            # None for single
    completed_lateral_ft: float  # sum of leg lengths (production / EUR)
    drilled_lateral_ft: float    # legs + turn arc (D&C cost)
    nearest_neighbor_spacing_ft: float
    setback_ft: float


@dataclass
class Feasibility:
    """Feasibility response — report what fit, never fail silently."""

    requested: int | None
    placed: int                  # number of WELLS placed
    legs: int                    # number of producing legs
    total_completed_ft: float
    total_drilled_ft: float
    note: str = ""


@dataclass
class Zone:
    """One target bench in a wine-rack stack."""

    formation: str          # formation_blueox code
    target_tvd_ft: float    # median landing TVD (parameter for now; warehouse later)


@dataclass
class ZoneResult:
    formation: str
    target_tvd_ft: float
    stagger_offset_ft: float   # cross-section phase shift applied to this zone
    wells: int
    legs: int


@dataclass
class WineRackReport:
    zones: list[ZoneResult]
    total_wells: int
    total_legs: int
    total_completed_ft: float
    stagger_ft: float
    # min 3-D distance between legs of any two ADJACENT zones (the wine-rack
    # diagonal): sqrt(horizontal_offset^2 + delta_TVD^2). Flags a frac-hit risk.
    min_interzone_offset_ft: float
    min_interzone_offset_ok: bool
    note: str = ""
