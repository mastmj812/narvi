"""Parcel ingest is GEOMETRY-ONLY: shapefile attributes are never read for
naming. Land counterparties' shapefiles carry arbitrary fields (fid, QQ,
Section, ...); guessing a deal name from them produced labels like "1"/"2"
that collided with unrelated saved deals. Labels are `<base>_<n>` placeholders
the user renames in the app."""

from __future__ import annotations

import io
import zipfile

import shapefile  # pyshp

from narvi.parcel import load_named_parcels

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
