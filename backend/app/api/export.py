"""Scenario export adapters. CSV/GeoJSON exports are client-side (the FC already
lives in the browser); shapefile is the exception because it's a zipped
multi-file binary format — the browser posts its FC here and gets the zip back.
Pure geometry, no DB."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from narvi import inventory_shapefile_zip
from narvi.shp_export import _clean_layer_name

from ..models import ShapefileExportRequest

router = APIRouter(prefix="/export", tags=["export"])


@router.post("/shapefile")
def shapefile(req: ShapefileExportRequest) -> Response:
    """Zipped shapefile (.shp/.shx/.dbf/.prj/.cpg) of the FC's inventory legs —
    pud/res/generated only, never PDP (GGX handoff). An FC with no inventory
    legs raises ValueError -> 400 via the app-level handler."""
    data = inventory_shapefile_zip(req.geojson, req.layer_name)
    base = _clean_layer_name(req.layer_name)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{base}.zip"'},
    )
