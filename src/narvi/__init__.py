"""Narvi geometry core — inventory-well scenario generator (Phase 0 library).

The geometry core (generate / parcel / placement / records) is DB-free. The
warehouse data layer (`narvi.warehouse`) is imported separately so that the core
stays importable without psycopg / a live connection."""

from .feasibility import (
    DirectionFeasibility,
    ScanConfig,
    parcel_feasibility,
    scan_configs,
)
from .generate import generate_scenario, generate_wine_rack, qualify_planned_names
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
from .shp_export import inventory_shapefile_zip
from .viz import gunbarrel_data, scenario_geojson

__all__ = [
    "DirectionFeasibility",
    "ScanConfig",
    "parcel_feasibility",
    "scan_configs",
    "generate_scenario",
    "generate_wine_rack",
    "qualify_planned_names",
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
    "inventory_shapefile_zip",
]
