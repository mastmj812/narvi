"""Warehouse sourcing — landing-TVD zones and the offset-well grid azimuth for an
AOI, so the front end can preview real numbers before generating."""

from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from narvi import parcel_from_geojson
from narvi.warehouse import lateral_azimuth_stats, zones_from_warehouse

from ..deps import get_conn

router = APIRouter(prefix="/warehouse", tags=["warehouse"])


class AoiRequest(BaseModel):
    parcel: dict                       # GeoJSON (Multi)Polygon, WGS84
    formations: list[str] | None = None
    buffer_ft: float = 5280.0


@router.post("/zones")
def zones(req: AoiRequest, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    parcel = parcel_from_geojson(req.parcel)
    zs, stats = zones_from_warehouse(
        conn, parcel, req.formations or [], req.buffer_ft, split_multimodal=True)
    return {
        "zones": [{"formation": z.formation, "target_tvd_ft": z.target_tvd_ft} for z in zs],
        "stats": [
            {"formation": s.formation, "wells": s.wells, "median_tvd_ft": s.median_tvd_ft,
             "multimodal": s.multimodal, "note": s.note}
            for s in stats
        ],
    }


@router.post("/azimuth")
def azimuth(req: AoiRequest, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    parcel = parcel_from_geojson(req.parcel)
    st = lateral_azimuth_stats(conn, parcel, req.buffer_ft)
    return {
        "azimuth_deg": st.azimuth_deg, "coherence": st.coherence, "wells": st.wells,
        "circ_std_deg": st.circ_std_deg, "confident": st.confident, "note": st.note,
    }
