"""Narvi geometry core — inventory-well scenario generator (Phase 0 library)."""

from .generate import generate_scenario, generate_wine_rack
from .parcel import load_named_parcels, load_parcel_zip, synthetic_section
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

__all__ = [
    "generate_scenario",
    "generate_wine_rack",
    "load_named_parcels",
    "load_parcel_zip",
    "synthetic_section",
    "Feasibility",
    "InventoryWell",
    "Leg",
    "ScenarioParams",
    "Turn",
    "WineRackReport",
    "Zone",
    "ZoneResult",
]
