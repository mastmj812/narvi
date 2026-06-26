"""Narvi geometry core — inventory-well scenario generator (Phase 0 library)."""

from .generate import generate_scenario
from .parcel import load_named_parcels, load_parcel_zip, synthetic_section
from .records import Feasibility, InventoryWell, Leg, ScenarioParams, Turn

__all__ = [
    "generate_scenario",
    "load_named_parcels",
    "load_parcel_zip",
    "synthetic_section",
    "Feasibility",
    "InventoryWell",
    "Leg",
    "ScenarioParams",
    "Turn",
]
