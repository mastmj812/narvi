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
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union
from shapely.validation import make_valid


def _valid_polygonal(g: BaseGeometry) -> Polygon | MultiPolygon:
    """Repair an invalid parcel (self-touching rings, bad orientation, slivers —
    rife in uploaded shapefiles) before any setback/clip op runs on it. An invalid
    boundary makes shapely's buffer/difference/intersection misbehave and can place
    a lateral OUTSIDE the unit. Keeps only the polygonal part of the repair."""
    if g.is_valid:
        return g
    fixed = make_valid(g)
    if isinstance(fixed, (Polygon, MultiPolygon)):
        return fixed
    polys = [p for p in getattr(fixed, "geoms", []) if isinstance(p, (Polygon, MultiPolygon))]
    if not polys:
        raise ValueError("parcel has no usable polygon area after geometry repair")
    return unary_union(polys)

WORK_EPSG = 32613  # UTM zone 13N, metres

def _transformer(src: CRS, dst_epsg: int):
    return Transformer.from_crs(src, CRS.from_epsg(dst_epsg), always_xy=True).transform


def _read_shapefile(data: bytes):
    """-> (list[ShapeRecord], field_names, src_crs). Reads members fully so the
    records survive the zip closing."""
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
        records = list(reader.iterShapeRecords())
        fields = [f[0] for f in reader.fields if f[0] != "DeletionFlag"]
    return records, fields, src


def load_parcel_zip(data: bytes) -> Polygon | MultiPolygon:
    """Parse a deal shapefile .zip -> a single dissolved parcel in UTM 13N (m).
    Dissolves every polygon — use load_named_parcels for a multi-deal bundle."""
    records, _, src = _read_shapefile(data)
    polys = [shape(sr.shape.__geo_interface__) for sr in records
             if sr.shape.__geo_interface__["type"] in ("Polygon", "MultiPolygon")]
    if not polys:
        raise ValueError("Shapefile contains no polygon geometry.")
    return _valid_polygonal(shp_transform(_transformer(src, WORK_EPSG), unary_union(polys)))


def parcel_from_geojson(geom: dict) -> Polygon | MultiPolygon:
    """A WGS84 GeoJSON (Multi)Polygon geometry -> a parcel in the work CRS (UTM
    13N, m). The inverse of viz's work->WGS84 transform; lets the app round-trip a
    parcel the front end holds in lon/lat back into the engine."""
    g = shape(geom)
    if g.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"expected a (Multi)Polygon, got {g.geom_type}")
    return _valid_polygonal(shp_transform(_transformer(CRS.from_epsg(4326), WORK_EPSG), g))


def load_named_parcels(data: bytes, base_label: str = "parcel") -> dict[str, Polygon | MultiPolygon]:
    """Deal shapefile .zip -> {label: parcel in UTM 13N}, one parcel per polygon
    record, in file order. The shapefile is consumed for its GEOMETRY ONLY —
    attributes are never read for naming (land shapefiles carry whatever fields
    the counterparty's GIS exported; guessing a deal name from them produced
    labels like "1"/"2" that collided with unrelated saved deals). Labels are
    `<base_label>_<n>` placeholders (just `<base_label>` for a single-polygon
    file); the user renames deals in the app."""
    records, _fields, src = _read_shapefile(data)
    tf = _transformer(src, WORK_EPSG)
    geoms = [shp_transform(tf, shape(sr.shape.__geo_interface__)) for sr in records
             if sr.shape.__geo_interface__["type"] in ("Polygon", "MultiPolygon")]
    if not geoms:
        raise ValueError("Shapefile contains no polygon geometry.")
    width = len(str(len(geoms)))
    return {
        (base_label if len(geoms) == 1 else f"{base_label}_{i:0{width}d}"): _valid_polygonal(g)
        for i, g in enumerate(geoms, start=1)
    }


def synthetic_section(side_ft: float = 5280.0,
                      center_lonlat: tuple[float, float] = (-103.8, 31.9)) -> Polygon:
    """A square 1-mile section (~640 ac) in UTM 13N (m), near the Delaware Basin —
    a stand-in parcel for engine dev until a real deal shapefile is supplied."""
    from .records import FT_PER_M

    x0, y0 = _transformer(CRS.from_epsg(4326), WORK_EPSG)(*center_lonlat)
    half = (side_ft / FT_PER_M) / 2.0
    return box(x0 - half, y0 - half, x0 + half, y0 + half)
