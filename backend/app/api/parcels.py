"""Parcel ingest — upload a deal shapefile .zip, get the named parcels back as
WGS84 GeoJSON for the map + a label to pick from."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from shapely.geometry import mapping

from narvi import load_named_parcels, synthetic_section
from narvi.viz import _to_wgs_geom

from ..models import ParcelInfo, ParcelsResponse

router = APIRouter(prefix="/parcels", tags=["parcels"])

_ACRE_M2 = 4046.8564224


@router.get("/synthetic", response_model=ParcelInfo)
def synthetic(side_ft: float = 5280.0, lon: float = -103.8, lat: float = 31.9) -> ParcelInfo:
    """A synthetic square section centered in the Loving/Reeves AOI — lets the app
    be exercised end-to-end (incl. warehouse sourcing) without a shapefile."""
    geom = synthetic_section(side_ft=side_ft, center_lonlat=(lon, lat))
    return ParcelInfo(
        label=f"synthetic {side_ft:.0f} ft section", area_ac=round(geom.area / _ACRE_M2, 1),
        geojson=mapping(_to_wgs_geom(geom)),
    )


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
