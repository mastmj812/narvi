"""Scenario FeatureCollection -> zipped ESRI shapefile (.shp/.shx/.dbf/.prj/.cpg).

The geologist-facing handoff (GGX/GeoGraphix ingests shapefiles, not GeoJSON).
Only INVENTORY sticks export — producing legs with category pud/res/generated.
PDP legs are existing production, not inventory, and context (near-parcel
background) wells never export anywhere; both are filtered here regardless of
what the caller passes in.

Geometry is the leg LineString verbatim in WGS84 (the FC is already lon-lat);
the .prj carries the ESRI GCS_WGS_1984 WKT so GGX georeferences it without
prompting. DBF names are capped at 10 chars by the format, hence the
abbreviated columns (COMPL_FT etc.) — same values as the CSV export columns.
"""

from __future__ import annotations

import io
import zipfile

import shapefile  # pyshp

# ESRI-flavored WGS84 WKT — what GGX/ArcGIS expect in a .prj
_WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)

# (dbf name <=10 chars, leg property, dbf type, size, decimals) — one row per
# producing leg, mirroring the CSV export's LEG_PROPS.
_FIELDS: list[tuple[str, str, str, int, int]] = [
    ("WELL_NAME", "well_name", "C", 64, 0),
    ("NOVI_NAME", "novi_wellname", "C", 64, 0),
    ("FORMATION", "formation", "C", 16, 0),
    ("CATEGORY", "category", "C", 12, 0),
    ("WELL_TYPE", "well_type", "C", 8, 0),
    ("RECON_STAT", "recon_status", "C", 16, 0),
    ("LEG_INDEX", "leg_index", "N", 4, 0),
    ("TVD_FT", "target_tvd_ft", "N", 12, 1),
    ("LENGTH_FT", "length_ft", "N", 12, 1),
    ("COMPL_FT", "completed_lateral_ft", "N", 12, 1),
    ("DRILL_FT", "drilled_lateral_ft", "N", 12, 1),
    ("AZIMUTH", "lateral_azimuth_deg", "N", 8, 2),
    ("SPACING_FT", "nearest_neighbor_spacing_ft", "N", 12, 1),
]


def _inventory_legs(fc: dict) -> list[dict]:
    """Producing legs that are actual inventory: not PDP, not context background."""
    out = []
    for f in fc.get("features", []):
        p = f.get("properties") or {}
        if p.get("kind") != "leg" or p.get("category") == "pdp" or p.get("context"):
            continue
        g = f.get("geometry") or {}
        if g.get("type") != "LineString" or len(g.get("coordinates", [])) < 2:
            continue
        out.append(f)
    return out


def _clean_layer_name(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.strip())
    return safe or "narvi_inventory"


def inventory_shapefile_zip(fc: dict, layer_name: str = "narvi_inventory") -> bytes:
    """Zipped polyline shapefile of the FC's inventory legs (pud/res/generated).

    Bundle FCs stamp each feature with `dsu` (source scenario name); when any
    leg carries it, a leading DSU column is added — same convention as the
    bundle CSV. Raises ValueError when the FC holds no inventory legs (e.g. a
    PDP-only curate), which the API surfaces as a 400.
    """
    legs = _inventory_legs(fc)
    if not legs:
        raise ValueError("no inventory sticks to export (PDP legs are excluded from the shapefile)")

    fields = list(_FIELDS)
    if any((f.get("properties") or {}).get("dsu") is not None for f in legs):
        fields.insert(0, ("DSU", "dsu", "C", 64, 0))

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYLINE)
    for name, _, ftype, size, dec in fields:
        w.field(name, ftype, size=size, decimal=dec)
    for f in legs:
        p = f["properties"]
        w.line([f["geometry"]["coordinates"]])
        record = []
        for _, prop, ftype, _, _ in fields:
            v = p.get(prop)
            record.append(("" if v is None else str(v)) if ftype == "C" else v)
        w.record(*record)
    w.close()

    base = _clean_layer_name(layer_name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}.shp", shp.getvalue())
        z.writestr(f"{base}.shx", shx.getvalue())
        z.writestr(f"{base}.dbf", dbf.getvalue())
        z.writestr(f"{base}.prj", _WGS84_PRJ)
        z.writestr(f"{base}.cpg", "UTF-8")
    return buf.getvalue()
