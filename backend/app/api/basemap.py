"""Serve the shared Protomaps PMTiles basemap with HTTP range support.

PMTiles reads via byte-range requests, so this honors the Range header (RFC 7233)
and answers 206 + Content-Range. Reuses the permian.pmtiles file vendored under
permian_type_curve/infra/basemap (see config.pmtiles_path). Mirrors erebor's
basemap router.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.config import settings

router = APIRouter(prefix="/basemap", tags=["basemap"])

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 256 * 1024


async def _file_chunks(path: Path, start: int, length: int) -> AsyncIterator[bytes]:
    remaining = length
    with path.open("rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/permian.pmtiles")
async def serve_pmtiles(request: Request) -> Response:
    path = settings.pmtiles_path
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PMTiles not found at {path}. Set PMTILES_PATH in backend/.env.",
        )
    file_size = path.stat().st_size
    common = {
        "Accept-Ranges": "bytes",
        "Content-Type": "application/vnd.pmtiles",
        "Cache-Control": "public, max-age=3600",
    }
    range_header = request.headers.get("range")
    if range_header is None:
        return FileResponse(path, headers=common)
    match = _RANGE_RE.match(range_header.strip())
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail=f"Malformed Range header: {range_header!r}",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    start_s, end_s = match.groups()
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Range out of bounds",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    length = end - start + 1
    headers = {
        **common,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(length),
    }
    return StreamingResponse(
        _file_chunks(path, start, length),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        headers=headers,
    )


@router.head("/permian.pmtiles")
async def head_pmtiles() -> Response:
    path = settings.pmtiles_path
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Type": "application/vnd.pmtiles",
            "Content-Length": str(path.stat().st_size),
        },
    )


def _serve_geojson(path: Path) -> Response:
    """Serve a vendored survey-grid GeoJSON overlay (blocks / sections).

    404 (not 500) when the file is absent — the overlay is optional and the
    frontend degrades gracefully by turning its toggle back off. The assets
    live in anduin's infra/basemap; see app.config for the paths.
    """
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"GeoJSON overlay not found at {path}.",
        )
    return FileResponse(
        path,
        media_type="application/geo+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/blocks_tx_nm.geojson")
async def serve_blocks() -> Response:
    return _serve_geojson(settings.blocks_geojson_path)


@router.get("/sections_tx_nm.geojson")
async def serve_sections() -> Response:
    return _serve_geojson(settings.sections_geojson_path)
