"""Parcel ingest — upload a deal shapefile .zip, get the named parcels back as
WGS84 GeoJSON for the map + a label to pick from."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from shapely.geometry import mapping

from narvi import load_named_parcels
from narvi.viz import _to_wgs_geom

from ..models import ParcelInfo, ParcelsResponse

router = APIRouter(prefix="/parcels", tags=["parcels"])

_ACRE_M2 = 4046.8564224


@router.post("/upload", response_model=ParcelsResponse)
async def upload(file: UploadFile = File(...)) -> ParcelsResponse:
    data = await file.read()
    try:
        parcels = load_named_parcels(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    out = [
        ParcelInfo(
            label=label, area_ac=round(geom.area / _ACRE_M2, 1),
            geojson=mapping(_to_wgs_geom(geom)),
        )
        for label, geom in sorted(parcels.items())
    ]
    return ParcelsResponse(parcels=out)
