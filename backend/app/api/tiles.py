"""Basin-wide PDP well-stick vector tiles (the anduin map pattern, straight off
the warehouse).

Source: curated.erebor_locations, PDP arm — materialized, GIST-indexed on
wellstick_geom, pre-filtered to producing horizontals in the Delaware/Midland.
PostGIS renders the tile server-side (ST_TileEnvelope -> ST_AsMVTGeom ->
ST_AsMVT); the envelope is transformed to 4326 for the intersects test so the
GIST index on wellstick_geom is used (never transform the column).

Zoom gating: z < POINTS_MIN_Z -> 204 (a basin-wide dump is megabytes),
z 6-8 -> one point per stick (`pdp_points`), z >= 9 -> full stick linestrings
(`pdp_lines`). No filters -> the ETag is static per tile, and the data refreshes
nightly, so tiles cache for an hour.

The matview is dropped by the quarterly Novi reload (intel_locations CASCADE);
until engineering_db's apply script re-creates it we return 503, which the
frontend treats as "layer unavailable" rather than an error storm.
"""

from __future__ import annotations

import hashlib

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from ..deps import get_conn

router = APIRouter(prefix="/wells", tags=["wells"])

POINTS_MIN_Z = 6
LINES_MIN_Z = 9
MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"
# bump to invalidate client tile caches when the SQL/props change
TILE_VERSION = "pdp-v1"
_CACHE_CONTROL = "public, max-age=3600"

_POINTS_SQL = """
WITH bounds AS (
  SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env
),
mvtgeom AS (
  SELECT
    el.unique_id AS api10,
    el.formation_blueox,
    el.operator,
    el.tvd,
    el.ll_ft,
    el.recon_status,
    ST_AsMVTGeom(
      ST_Transform(ST_PointOnSurface(el.wellstick_geom), 3857),
      (SELECT env FROM bounds), 4096, 64, true
    ) AS geom
  FROM curated.erebor_locations el
  WHERE el.category = 'PDP'
    AND el.wellstick_geom IS NOT NULL
    AND ST_Intersects(el.wellstick_geom,
                      ST_Transform((SELECT env FROM bounds), 4326))
)
SELECT ST_AsMVT(mvtgeom.*, 'pdp_points', 4096, 'geom')
FROM mvtgeom WHERE geom IS NOT NULL
"""

_LINES_SQL = """
WITH bounds AS (
  SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env
),
mvtgeom AS (
  SELECT
    el.unique_id AS api10,
    el.formation_blueox,
    el.operator,
    el.tvd,
    el.ll_ft,
    el.recon_status,
    ST_AsMVTGeom(
      ST_Transform(el.wellstick_geom, 3857),
      (SELECT env FROM bounds), 4096, 64, true
    ) AS geom
  FROM curated.erebor_locations el
  WHERE el.category = 'PDP'
    AND el.wellstick_geom IS NOT NULL
    AND ST_Intersects(el.wellstick_geom,
                      ST_Transform((SELECT env FROM bounds), 4326))
)
SELECT ST_AsMVT(mvtgeom.*, 'pdp_lines', 4096, 'geom')
FROM mvtgeom WHERE geom IS NOT NULL
"""


def _tile_etag(z: int, x: int, y: int) -> str:
    h = hashlib.sha256(f"{TILE_VERSION}/{z}/{x}/{y}".encode()).hexdigest()
    return f'W/"{h[:16]}"'


@router.get(
    "/tiles/{z}/{x}/{y}.mvt",
    responses={
        200: {"content": {MVT_CONTENT_TYPE: {}}},
        204: {"description": "No features at this tile/zoom"},
        503: {"description": "curated.erebor_locations missing (Novi reload window)"},
    },
)
def pdp_tile(
    request: Request,
    z: int = Path(ge=0, le=22),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
    conn: psycopg.Connection = Depends(get_conn),
) -> Response:
    if x >= (1 << z) or y >= (1 << z):
        raise HTTPException(status_code=400, detail="tile coords out of range for z")

    etag = _tile_etag(z, x, y)
    headers = {"ETag": etag, "Cache-Control": _CACHE_CONTROL}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if z < POINTS_MIN_Z:
        return Response(status_code=204, headers=headers)

    sql = _LINES_SQL if z >= LINES_MIN_Z else _POINTS_SQL
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"z": z, "x": x, "y": y})
            row = cur.fetchone()
    except psycopg.errors.UndefinedTable:
        raise HTTPException(
            status_code=503,
            detail="curated.erebor_locations is missing — re-run the "
                   "engineering_db apply script after the Novi reload")

    payload: bytes = bytes(row[0]) if row and row[0] is not None else b""
    if not payload:
        return Response(status_code=204, headers=headers)
    return Response(content=payload, media_type=MVT_CONTENT_TYPE, headers=headers)
