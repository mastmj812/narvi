"""Parcel ingest + working CRS.

A deal upload (.zip shapefile or .gpkg GeoPackage) or a synthetic section ->
parcel polygons in the planar WORK CRS (UTM 13N, metres). UTM 13N (EPSG:32613)
spans the Permian across both TX and NM, so length/area math is in metres
throughout the engine and converted to feet only at the human boundary (see
records.FT_PER_M).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

import shapefile  # pyshp
from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union
from shapely.validation import make_valid

from .gpkg_reader import pick_label, read_gpkg, sniff_format, split_roles


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


@dataclass
class ParcelRecord:
    """One deal parcel from an upload: geometry in the work CRS plus whatever
    land attributes the file carried (empty for shapefile zips). `tracts` holds
    the Tract rows spatially assigned to this DSU (gpkg deliverables only) —
    display/pass-through data; nothing in the engine consumes it."""

    label: str
    geom: Polygon | MultiPolygon               # WORK_EPSG (UTM 13N, m)
    attributes: dict[str, Any] = field(default_factory=dict)
    tracts: list[dict[str, Any]] = field(default_factory=list)


def load_parcels(data: bytes, base_label: str = "parcel") -> list[ParcelRecord]:
    """Deal upload (.zip shapefile or .gpkg GeoPackage) -> parcel records.

    zip  -> exactly load_named_parcels (geometry-only, placeholder labels).
    gpkg -> the land-department deliverable: rows typed 'DSU' become parcels
            (attributes carried along) and 'Tract' rows attach to their DSU by
            max-area intersection. Files with no Type column behave like a
            shapefile (every polygon a parcel, placeholder labels); a
            tract-only file falls back to tracts-as-parcels rather than 400ing.
    """
    kind = sniff_format(data)
    if kind == "zip":
        return [ParcelRecord(label=lbl, geom=g)
                for lbl, g in load_named_parcels(data, base_label).items()]
    if kind == "gpkg":
        return _load_parcels_gpkg(data, base_label)
    raise ValueError("Upload a zipped shapefile (.zip) or a GeoPackage (.gpkg).")


def _load_parcels_gpkg(data: bytes, base_label: str) -> list[ParcelRecord]:
    layers = read_gpkg(data)
    prim: list[tuple[dict[str, Any], Polygon | MultiPolygon]] = []
    tracts: list[tuple[dict[str, Any], Polygon | MultiPolygon]] = []
    for layer in layers:
        tf = _transformer(layer.crs, WORK_EPSG)
        dsus, trs, generic = split_roles(layer.features)
        # DSU rows are the mapped units; attribute-less files (no Type column)
        # put everything in `generic`. A tract-only file: tracts become parcels.
        chosen = dsus if dsus else generic if generic else trs
        kept_tracts = trs if chosen is not trs else []
        for f in chosen:
            prim.append((f.attributes, _valid_polygonal(shp_transform(tf, f.geometry))))
        for f in kept_tracts:
            tracts.append((f.attributes, _valid_polygonal(shp_transform(tf, f.geometry))))
    if not prim:
        raise ValueError("GeoPackage contains no polygon features.")

    # Labels: an attribute name (DSU_Num etc.) is slugged UNDER the file stem so
    # two deals' "DSU 31" never collide ("toucan_v2_dsu_31"); no usable
    # attribute -> the same placeholder scheme as shapefile zips.
    width = len(str(len(prim)))
    used: set[str] = set()
    records: list[ParcelRecord] = []
    for i, (attrs, geom) in enumerate(prim, start=1):
        slug = re.sub(r"[^a-z0-9]+", "_", pick_label(attrs, "").lower()).strip("_")
        if slug:
            label = f"{base_label}_{slug}"
        else:
            label = base_label if len(prim) == 1 else f"{base_label}_{i:0{width}d}"
        cand, n = label, 2
        while cand in used:
            cand = f"{label}_{n}"
            n += 1
        used.add(cand)
        records.append(ParcelRecord(label=cand, geom=geom, attributes=dict(attrs)))

    # Tract -> DSU assignment by max-area intersection (the suite's
    # overlap-not-distance convention; DSU_Num/Section string matching is
    # implicit and fragile). Non-overlapping tracts are dropped.
    for j, (attrs, tgeom) in enumerate(tracts, start=1):
        best, best_a = None, 0.0
        for rec in records:
            a = rec.geom.intersection(tgeom).area
            if a > best_a:
                best, best_a = rec, a
        if best is not None:
            best.tracts.append(
                {"label": pick_label(attrs, _tract_fallback_label(attrs, j)),
                 "attributes": dict(attrs)})
    return records


def _tract_fallback_label(attrs: dict[str, Any], n: int) -> str:
    """Tract rows carry Section/Block, not a name column — 'Sec 33 Blk 1' reads
    better on the parcel card than 'tract_3'."""
    low = {k.strip().casefold(): v for k, v in attrs.items()}
    sec, blk = low.get("section"), low.get("block")
    if sec is not None and str(sec).strip():
        label = f"Sec {str(sec).strip()}"
        if blk is not None and str(blk).strip():
            label += f" Blk {str(blk).strip()}"
        return label
    return f"tract_{n}"


def synthetic_section(side_ft: float = 5280.0,
                      center_lonlat: tuple[float, float] = (-103.8, 31.9)) -> Polygon:
    """A square 1-mile section (~640 ac) in UTM 13N (m), near the Delaware Basin —
    a stand-in parcel for engine dev until a real deal shapefile is supplied."""
    from .records import FT_PER_M

    x0, y0 = _transformer(CRS.from_epsg(4326), WORK_EPSG)(*center_lonlat)
    half = (side_ft / FT_PER_M) / 2.0
    return box(x0 - half, y0 - half, x0 + half, y0 + half)
