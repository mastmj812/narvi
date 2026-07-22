"""Scenario generation — parcel + params -> inventory wells + map GeoJSON +
gun-barrel data. Pure geometry unless the request asks to source TVD/azimuth."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from narvi import parcel_from_geojson, scan_configs

from ..engine import generate_response
from ..models import (
    GenerateRequest,
    GenerateResponse,
    ScanConfigModel,
    ScanRequest,
    ScanResponse,
)

router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        return generate_response(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/generate/scan", response_model=ScanResponse)
def scan(req: ScanRequest) -> ScanResponse:
    """Configuration scan — azimuth x well-type x spacing through the real
    placement engine, ranked by completed footage. Pure geometry (no DB): the
    azimuth candidates come from /parcels/feasibility."""
    parcel = parcel_from_geojson(req.parcel)
    base = req.params.to_narvi()
    azimuths = [(a.label, a.azimuth_deg) for a in req.azimuths]
    if not azimuths:
        raise HTTPException(status_code=400, detail="scan needs at least one azimuth")
    kwargs = {"spacings": tuple(req.spacings)} if req.spacings else {}
    configs = scan_configs(parcel, base, azimuths, **kwargs)
    return ScanResponse(configs=[
        ScanConfigModel(
            azimuth_label=c.azimuth_label, azimuth_deg=c.azimuth_deg,
            well_type=c.well_type, spacing_ft=c.spacing_ft, wells=c.wells,
            legs=c.legs, completed_ft=c.completed_ft, ft_per_well=c.ft_per_well,
            note=c.note)
        for c in configs
    ])
