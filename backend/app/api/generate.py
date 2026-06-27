"""Scenario generation — parcel + params -> inventory wells + map GeoJSON +
gun-barrel data. Pure geometry unless the request asks to source TVD/azimuth."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..engine import generate_response
from ..models import GenerateRequest, GenerateResponse

router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        return generate_response(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
