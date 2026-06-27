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

    def to_narvi(self) -> Zone:
        return Zone(formation=self.formation, target_tvd_ft=self.target_tvd_ft)


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


class SaveScenarioRequest(BaseModel):
    deal_id: str
    scenario_id: str
    name: str | None = None
    generate: GenerateRequest                  # regenerated server-side, then persisted


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
