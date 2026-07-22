"""Pydantic request/response models for the narvi API.

Thin wrappers over the narvi dataclasses: ScenarioParamsModel <-> ScenarioParams,
zones, and the generate request/response. Geometry crosses the wire as GeoJSON
(WGS84); the engine reprojects to its UTM 13N work CRS.
"""

from __future__ import annotations

from typing import Any, Literal

from narvi import ScenarioParams, Zone
from pydantic import BaseModel, Field


class ScenarioParamsModel(BaseModel):
    """Generation inputs. formation/target_tvd_ft are only used for single-zone
    runs; a wine-rack supplies them per Zone."""

    spacing_ft: float
    setback_ft: float
    formation: str = ""
    target_tvd_ft: float = 0.0
    azimuth_deg: float | None = None          # None => auto (grid or long axis)
    well_type: Literal["single", "uturn"] = "single"
    objective: Literal["max_lateral", "max_count"] = "max_lateral"
    drill_from: Literal["auto", "north", "south"] = "auto"   # U-turn surface side
    anchor: Literal["auto", "west", "east", "center"] = "auto"  # where rows hang
    min_lateral_ft: float = 4000.0
    uturn_min_leg_to_leg_ft: float = 990.0
    setback_ns_ft: float | None = None
    setback_ew_ft: float | None = None
    scenario_id: str = "s1"
    deal_id: str = "demo"

    def to_narvi(self) -> ScenarioParams:
        return ScenarioParams(**self.model_dump())


class ZoneModel(BaseModel):
    formation: str
    target_tvd_ft: float
    spacing_ft: float | None = None        # per-bench leg-to-leg; None -> base spacing

    def to_narvi(self) -> Zone:
        return Zone(formation=self.formation, target_tvd_ft=self.target_tvd_ft,
                    spacing_ft=self.spacing_ft)


class GenerateRequest(BaseModel):
    parcel: dict[str, Any]                    # GeoJSON (Multi)Polygon geometry, WGS84
    params: ScenarioParamsModel
    mode: Literal["single", "winerack"] = "single"
    zones: list[ZoneModel] | None = None      # explicit wine-rack benches
    formations: list[str] | None = None       # benches to source from the warehouse
    source_tvd: bool = False                   # wine-rack: source zone TVDs from warehouse
    source_azimuth: bool = False               # adopt the offset-well grid azimuth
    buffer_ft: float = 5280.0


class GenerateResponse(BaseModel):
    mode: str
    placed_wells: int
    placed_legs: int
    azimuth_deg: float | None
    summary: str                               # feasibility / wine-rack note
    warehouse_notes: list[str] = Field(default_factory=list)
    geojson: dict[str, Any]                    # FeatureCollection for the map
    gunbarrel: dict[str, Any]                  # cross-section data


class ParcelInfo(BaseModel):
    label: str
    area_ac: float
    geojson: dict[str, Any]                    # WGS84 (Multi)Polygon


class ParcelsResponse(BaseModel):
    parcels: list[ParcelInfo]


class InventoryRequest(BaseModel):
    parcel: dict[str, Any]                     # GeoJSON (Multi)Polygon, WGS84
    # spatial pre-filter before the co-extent membership test; wide so any lateral
    # overlapping the unit is fetched (membership decides, not the buffer)
    buffer_ft: float = 5280.0
    categories: list[str] = ["pdp", "pud", "res"]
    # near-parcel PDP background (context=true wells). Default OFF: the basin-wide
    # PDP tile layer is the map context, and the gun-barrel is a UNIT cross-section
    # — offset wells a mile out just clutter it (user feedback, bro_time 1 4-9).
    # Context wells never persist or export.
    context_radius_ft: float | None = None


class BenchInfoModel(BaseModel):
    formation: str
    median_tvd_ft: float | None
    n_pdp: int
    n_pud: int
    n_res: int
    suggested_spacing_ft: float | None
    note: str
    n_supported: int | None = None   # pud/res sticks with offset support (sql/30); null in dev menu


class InventoryResponse(BaseModel):
    well_count: int
    geojson: dict[str, Any]                     # parcel + existing PDP/PUD/RES legs
    gunbarrel: dict[str, Any]
    benches: list[BenchInfoModel]               # overlap inventory (curate menu)
    dev_benches: list[BenchInfoModel]           # area-developable benches (override menu)


class FeasibilityRequest(BaseModel):
    """Parcel feasibility card — what each realistic bearing can hold. The grid
    azimuth is sourced (confidence-gated) unless the client stipulates one."""

    parcel: dict[str, Any]                     # GeoJSON (Multi)Polygon, WGS84
    setback_ft: float = 330.0
    setback_ns_ft: float | None = None
    setback_ew_ft: float | None = None
    min_lateral_ft: float | None = 4000.0
    grid_azimuth_deg: float | None = None      # None -> source from the warehouse
    buffer_ft: float = 5280.0


class DirectionFeasibilityModel(BaseModel):
    label: str                                 # 'grid' | 'long-axis'
    azimuth_deg: float
    max_lateral_ft: float
    cross_extent_ft: float
    note: str


class FeasibilityResponse(BaseModel):
    directions: list[DirectionFeasibilityModel]


class ScanRequest(BaseModel):
    """Configuration scan: sweep azimuth x well-type x spacing through the real
    placement engine, ranked by completed footage. Pure geometry — the client
    passes the feasibility directions (which carry the sourced grid azimuth)."""

    parcel: dict[str, Any]                     # GeoJSON (Multi)Polygon, WGS84
    params: ScenarioParamsModel                # base (setbacks, min lateral, floor)
    azimuths: list[DirectionFeasibilityModel]  # from /parcels/feasibility
    spacings: list[float] | None = None        # None -> engine defaults


class ScanConfigModel(BaseModel):
    azimuth_label: str
    azimuth_deg: float
    well_type: str
    spacing_ft: float
    wells: int
    legs: int
    completed_ft: float
    ft_per_well: float
    note: str


class ScanResponse(BaseModel):
    configs: list[ScanConfigModel]


class SaveScenarioRequest(BaseModel):
    deal_id: str
    scenario_id: str
    name: str | None = None
    generate: GenerateRequest                  # regenerated server-side, then persisted
    culled_wells: list[str] = []               # per-well culls (well_name) baked out of
                                               # the persisted plan — the forecaster
                                               # hand-off must not carry culled wells


class SaveComposedRequest(BaseModel):
    """Persist a composed plan: per bench the user either adopts the Novi baseline
    ('novi'), designs their own wells ('generate'), or drops it ('off'). The kept
    Novi inventory and the generated wells persist together as ONE scenario — the
    unified successor to the curate/override either-or saves."""

    deal_id: str
    scenario_id: str
    name: str | None = None
    parcel: dict[str, Any]                     # GeoJSON (Multi)Polygon, WGS84
    bench_sources: dict[str, str]              # formation -> novi | generate | off
    categories: list[str] = ["pdp", "pud", "res"]   # active display/persist categories
    culled_wells: list[str] = []               # per-well culls (well_name) baked out
    params: ScenarioParamsModel                # deal-level generator params
    zones: list[ZoneModel] = []                # per-bench TVD/spacing (generate benches)
    source_azimuth: bool = True
    buffer_ft: float = 5280.0


class SaveCurateRequest(BaseModel):
    """Persist a curated Novi-inventory baseline: the existing wells in the parcel,
    trimmed to the kept benches + active categories (not a generated run)."""

    deal_id: str
    scenario_id: str
    name: str | None = None
    parcel: dict[str, Any]                     # GeoJSON (Multi)Polygon, WGS84
    kept_benches: list[str]                    # formation_blueox codes kept
    categories: list[str] = ["pdp", "pud", "res"]   # active categories
    culled_wells: list[str] = []               # per-well culls (well_name) to drop
    buffer_ft: float = 5280.0                  # match /parcels/inventory: same fetch,
                                               # same membership, same saved set


class ShapefileExportRequest(BaseModel):
    """The browser's current (post-cull, post-filter) FC -> zipped shapefile of
    the inventory legs only (PDP/context filtered server-side). layer_name
    becomes the .shp/.dbf/... basename inside the zip."""

    geojson: dict[str, Any]                    # scenario/bundle FeatureCollection, WGS84
    layer_name: str = "narvi_inventory"


class ScenarioSummary(BaseModel):
    deal_id: str
    scenario_id: str
    name: str | None
    well_type: str
    objective: str
    total_wells: int | None
    total_legs: int | None
    total_completed_ft: float | None
    azimuth_deg: float | None
