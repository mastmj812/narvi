"""Narvi geometry core — inventory-well scenario generator (Phase 0 library).

The geometry core (generate / parcel / placement / records) is DB-free. The
warehouse data layer (`narvi.warehouse`) is imported separately so that the core
stays importable without psycopg / a live connection."""

from .generate import generate_scenario, generate_wine_rack
from .parcel import (
    load_named_parcels,
    load_parcel_zip,
    parcel_from_geojson,
    synthetic_section,
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
from .viz import gunbarrel_data, scenario_geojson

__all__ = [
    "generate_scenario",
    "generate_wine_rack",
    "load_named_parcels",
    "load_parcel_zip",
    "parcel_from_geojson",
    "synthetic_section",
    "Feasibility",
    "InventoryWell",
    "Leg",
    "ScenarioParams",
    "Turn",
    "WineRackReport",
    "Zone",
    "ZoneResult",
    "scenario_geojson",
    "gunbarrel_data",
]
