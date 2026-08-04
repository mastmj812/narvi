"""Parcel ingest.

Shapefile (.zip) ingest is GEOMETRY-ONLY: attributes are never read for
naming. Land counterparties' shapefiles carry arbitrary fields (fid, QQ,
Section, ...); guessing a deal name from them produced labels like "1"/"2"
that collided with unrelated saved deals. Labels are `<base>_<n>` placeholders
the user renames in the app.

GeoPackage (.gpkg) ingest follows the land department's deliverable convention
(Toucan v2): one layer, a `Type` column discriminating DSU vs Tract rows, and a
DSU_Num naming column — those ARE read (the label stays slugged under the file
stem, so cross-deal collisions can't recur). Attribute-less gpkg files behave
exactly like a shapefile."""

from __future__ import annotations

import io
import sqlite3
import struct
import zipfile
from pathlib import Path
from typing import Any

import shapefile  # pyshp
import shapely.wkb
from shapely.geometry import Polygon

from narvi.parcel import load_named_parcels, load_parcels

# ~1 sq mile in degrees near the Delaware Basin AOI
_D = 0.017


def _square(lon: float, lat: float) -> list[list[float]]:
    return [[lon, lat], [lon + _D, lat], [lon + _D, lat + _D], [lon, lat + _D], [lon, lat]]


def _zip_shapefile(polys: list[list[list[float]]], field: str, values: list[str]) -> bytes:
    """Author an in-memory zipped shapefile with a name-bearing attribute field
    (the thing ingest must IGNORE). No .prj -> reader assumes EPSG:4326."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf) as w:
        w.field(field, "C")
        for poly, val in zip(polys, values):
            w.poly([poly])
            w.record(val)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("deal.shp", shp.getvalue())
        z.writestr("deal.shx", shx.getvalue())
        z.writestr("deal.dbf", dbf.getvalue())
    return out.getvalue()


def test_attributes_are_ignored_for_naming():
    data = _zip_shapefile(
        [_square(-103.8, 31.9), _square(-103.7, 31.9)],
        field="dealname", values=["BRAVEHEART", "WHITE KNIFE"],
    )
    parcels = load_named_parcels(data, base_label="castaway")
    assert list(parcels) == ["castaway_1", "castaway_2"]   # file order, not attrs


def test_single_polygon_gets_bare_base_label():
    data = _zip_shapefile([_square(-103.8, 31.9)], field="name", values=["X"])
    parcels = load_named_parcels(data, base_label="castaway")
    assert list(parcels) == ["castaway"]


def test_default_base_label_and_geometry_roundtrip():
    data = _zip_shapefile([_square(-103.8, 31.9)], field="fid", values=["1"])
    parcels = load_named_parcels(data)
    assert list(parcels) == ["parcel"]
    (geom,) = parcels.values()
    # ~1-mile square -> ~640 ac in the UTM 13N work CRS (loose bound: degrees
    # aren't isotropic at 31.9N)
    acres = geom.area / 4046.8564224
    assert 500 < acres < 800


# --- GeoPackage ------------------------------------------------------------

def _gpkg_blob(geom: Polygon, *, empty: bool = False, envelope: bytes = b"") -> bytes:
    """Author a GPKG binary geometry blob: magic 'GP', version 0, flags
    (little-endian byte order + envelope indicator), srs_id, then WKB."""
    env_code = {0: 0, 32: 1}[len(envelope)]
    flags = 0x01 | (env_code << 1) | (0x10 if empty else 0)
    return b"GP\x00" + bytes([flags]) + struct.pack("<i", 4326) + envelope + shapely.wkb.dumps(geom)


def _make_gpkg(tmp_path: Path, rows: list[tuple[dict[str, Any], bytes]],
               layer: str = "Toucan v2") -> bytes:
    """Author a minimal spec-shaped GeoPackage: the gpkg_* registry tables plus
    one feature table whose columns are the union of the rows' attribute keys."""
    path = tmp_path / "fixture.gpkg"
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL,
            srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL,
            description TEXT);
        INSERT INTO gpkg_spatial_ref_sys VALUES
            ('WGS 84', 4326, 'EPSG', 4326, 'unused-by-reader', NULL);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY,
            data_type TEXT NOT NULL, identifier TEXT, description TEXT,
            last_change DATETIME, min_x DOUBLE, min_y DOUBLE, max_x DOUBLE,
            max_y DOUBLE, srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL,
            column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL);
    """)
    cols: list[str] = []
    for attrs, _ in rows:
        for k in attrs:
            if k not in cols:
                cols.append(k)
    col_ddl = "".join(f', "{c}" TEXT' for c in cols)
    q = layer.replace('"', '""')
    conn.execute(f'CREATE TABLE "{q}" (fid INTEGER PRIMARY KEY AUTOINCREMENT,'
                 f' geom BLOB{col_ddl})')
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id)"
                 " VALUES (?, 'features', ?, 4326)", (layer, layer))
    # deliberately declare MULTIPOLYGON while storing plain POLYGON blobs —
    # the reader must classify per blob, never trust the declaration
    conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'MULTIPOLYGON', 4326, 0, 0)",
                 (layer,))
    for attrs, blob in rows:
        ph = ", ".join(["?"] * (1 + len(cols)))
        conn.execute(
            f'INSERT INTO "{q}" (geom{"".join(f", \"{c}\"" for c in cols)}) VALUES ({ph})',
            [blob] + [attrs.get(c) for c in cols])
    conn.commit()
    conn.close()
    return path.read_bytes()


def _sq(lon: float, lat: float) -> Polygon:
    return Polygon(_square(lon, lat))


def test_gpkg_without_attributes_behaves_like_a_shapefile(tmp_path):
    data = _make_gpkg(tmp_path, [({}, _gpkg_blob(_sq(-103.8, 31.9))),
                                 ({}, _gpkg_blob(_sq(-103.7, 31.9)))], layer="Toucan")
    parcels = load_parcels(data, base_label="toucan")
    assert [p.label for p in parcels] == ["toucan_1", "toucan_2"]
    assert all(p.attributes == {} and p.tracts == [] for p in parcels)
    acres = parcels[0].geom.area / 4046.8564224
    assert 500 < acres < 800


def test_gpkg_dsu_rows_become_parcels_with_tracts_attached(tmp_path):
    # Toucan v2 shape: one layer, Type column, DSU_Num naming, depth/WI attrs.
    # DSU at (-103.8) contains its tract; the second DSU has no tract.
    rows = [
        ({"Type": "Tract", "Section": "33", "Min_Depth": "Surface",
          "Max_Depth": "9,515", "Tract_WI": "1.0"}, _gpkg_blob(_sq(-103.8, 31.9))),
        ({"Type": "DSU", "DSU_Num": "33", "Min_Depth": "Surface",
          "Max_Depth": "9,515'", "DSU_WI": "1.0"}, _gpkg_blob(_sq(-103.8, 31.9))),
        ({"Type": "DSU", "DSU_Num": "12-15", "DSU_WI": "0.5"},
         _gpkg_blob(_sq(-103.6, 31.9))),
    ]
    parcels = load_parcels(_make_gpkg(tmp_path, rows), base_label="toucan_v2")
    assert [p.label for p in parcels] == ["toucan_v2_dsu_33", "toucan_v2_dsu_12_15"]
    assert parcels[0].attributes["Max_Depth"] == "9,515'"     # raw text, uninterpreted
    assert len(parcels[0].tracts) == 1
    assert parcels[0].tracts[0]["label"] == "Sec 33"          # Section fallback label
    assert parcels[0].tracts[0]["attributes"]["Section"] == "33"
    assert parcels[1].tracts == []


def test_gpkg_duplicate_dsu_num_labels_are_deduped(tmp_path):
    rows = [({"Type": "DSU", "DSU_Num": "7"}, _gpkg_blob(_sq(-103.8, 31.9))),
            ({"Type": "DSU", "DSU_Num": "7"}, _gpkg_blob(_sq(-103.7, 31.9)))]
    parcels = load_parcels(_make_gpkg(tmp_path, rows), base_label="deal")
    assert [p.label for p in parcels] == ["deal_dsu_7", "deal_dsu_7_2"]


def test_gpkg_z_geometry_is_flattened_and_empty_flag_skipped(tmp_path):
    zpoly = Polygon([(x, y, 100.0) for x, y in _square(-103.8, 31.9)])
    rows = [({}, _gpkg_blob(zpoly)),
            ({}, _gpkg_blob(_sq(-103.7, 31.9), empty=True))]
    parcels = load_parcels(_make_gpkg(tmp_path, rows), base_label="zdeal")
    assert len(parcels) == 1                                  # empty-flag row skipped
    assert parcels[0].label == "zdeal"
    assert not parcels[0].geom.has_z


def test_zip_path_is_unchanged_through_load_parcels():
    data = _zip_shapefile(
        [_square(-103.8, 31.9), _square(-103.7, 31.9)],
        field="dealname", values=["BRAVEHEART", "WHITE KNIFE"],
    )
    parcels = load_parcels(data, base_label="castaway")
    # zip ingest stays geometry-only: attributes NEVER name a shapefile deal
    assert [p.label for p in parcels] == ["castaway_1", "castaway_2"]
    assert all(p.attributes == {} for p in parcels)


def test_not_a_zip_or_gpkg_raises():
    try:
        load_parcels(b"not a spatial file at all")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert ".zip" in str(exc) and ".gpkg" in str(exc)
