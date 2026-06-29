"""Parcel ingest — upload a deal shapefile .zip, get the named parcels back as
WGS84 GeoJSON for the map + a label to pick from."""

from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from shapely.geometry import mapping

from narvi import (
    gunbarrel_data,
    load_named_parcels,
    parcel_from_geojson,
    scenario_geojson,
    synthetic_section,
)
from narvi.viz import _to_wgs_geom
from narvi.warehouse import available_benches, bench_summary, inventory_from_warehouse

from ..deps import get_conn
from ..models import (
    BenchInfoModel,
    InventoryRequest,
    InventoryResponse,
    ParcelInfo,
    ParcelsResponse,
)

router = APIRouter(prefix="/parcels", tags=["parcels"])

_ACRE_M2 = 4046.8564224


@router.post("/inventory", response_model=InventoryResponse)
def inventory(req: InventoryRequest, conn: psycopg.Connection = Depends(get_conn)) -> InventoryResponse:
    """Existing inventory in/around a parcel — PDP producers + Novi PUD/RES sticks
    as InventoryWells (the curate baseline) + the bench menu. Drives the initial
    map + gun-barrel before any curation."""
    parcel = parcel_from_geojson(req.parcel)
    # wide pre-filter so any lateral overlapping the unit is fetched; membership is
    # then decided by co-extent overlap inside inventory_from_warehouse.
    wells = inventory_from_warehouse(conn, parcel, 5280.0, tuple(req.categories))
    benches = bench_summary(wells)                          # overlap inventory -> curate
    # Override designs NEW development, so its menu is the AREA's developable benches
    # (producing TVD control within a buffer), not just what physically overlaps the
    # unit — e.g. WCA with plenty of nearby PDP but no well crossing this parcel.
    dev = available_benches(conn, parcel, buffer_ft=5280.0)

    def _bm(b):
        return BenchInfoModel(
            formation=b.formation, median_tvd_ft=b.median_tvd_ft, n_pdp=b.n_pdp,
            n_pud=b.n_pud, n_res=b.n_res, suggested_spacing_ft=b.suggested_spacing_ft,
            note=b.note)

    return InventoryResponse(
        well_count=len(wells),
        geojson=scenario_geojson(parcel, None, wells),
        gunbarrel=gunbarrel_data(wells),
        benches=[_bm(b) for b in benches],
        dev_benches=[_bm(b) for b in dev],
    )


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
