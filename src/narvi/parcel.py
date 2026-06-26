"""Parcel ingest + working CRS.

A deal shapefile (.zip) or a synthetic section -> a single dissolved parcel
polygon in the planar WORK CRS (UTM 13N, metres). UTM 13N (EPSG:32613) spans the
Permian across both TX and NM, so length/area math is in metres throughout the
engine and converted to feet only at the human boundary (see records.FT_PER_M).
"""

from __future__ import annotations

import io
import zipfile

import shapefile  # pyshp
from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union

WORK_EPSG = 32613  # UTM zone 13N, metres


def _transformer(src: CRS, dst_epsg: int):
    return Transformer.from_crs(src, CRS.from_epsg(dst_epsg), always_xy=True).transform


def load_parcel_zip(data: bytes) -> Polygon | MultiPolygon:
    """Parse a deal shapefile .zip -> dissolved parcel polygon in UTM 13N (m)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        shp = next((n for n in names if n.lower().endswith(".shp")), None)
        if not shp:
            raise ValueError("No .shp found in the uploaded zip.")
        stem = shp[:-4].lower()

        def member(ext: str) -> io.BytesIO | None:
            for n in names:
                if n.lower() == stem + ext:
                    return io.BytesIO(z.read(n))
            return None

        prj = member(".prj")
        src = CRS.from_wkt(prj.read().decode("utf-8", "replace")) if prj else CRS.from_epsg(4326)
        reader = shapefile.Reader(shp=member(".shp"), dbf=member(".dbf"), shx=member(".shx"))
        polys = [shape(sr.__geo_interface__) for sr in reader.iterShapes()
                 if sr.__geo_interface__["type"] in ("Polygon", "MultiPolygon")]

    if not polys:
        raise ValueError("Shapefile contains no polygon geometry.")
    parcel = unary_union(polys)
    return shp_transform(_transformer(src, WORK_EPSG), parcel)


def synthetic_section(side_ft: float = 5280.0,
                      center_lonlat: tuple[float, float] = (-103.8, 31.9)) -> Polygon:
    """A square 1-mile section (~640 ac) in UTM 13N (m), near the Delaware Basin —
    a stand-in parcel for engine dev until a real deal shapefile is supplied."""
    from .records import FT_PER_M

    x0, y0 = _transformer(CRS.from_epsg(4326), WORK_EPSG)(*center_lonlat)
    half = (side_ft / FT_PER_M) / 2.0
    return box(x0 - half, y0 - half, x0 + half, y0 + half)
