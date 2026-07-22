"""inventory_shapefile_zip — FC -> zipped shapefile of inventory legs only.

Pure/DB-free: FCs are built by hand with the same properties scenario_geojson
emits. The zip is read back with pyshp to assert the filter (no PDP, no
context) and the DBF column mapping actually round-trip.
"""

import io
import zipfile

import pytest
import shapefile

from narvi import inventory_shapefile_zip


def _leg(name: str, category: str, *, context: bool = False, dsu: str | None = None) -> dict:
    props = {
        "kind": "leg", "well_name": name, "well_type": "single",
        "category": category, "novi_wellname": None, "recon_status": None,
        "context": context, "formation": "WCA_1", "target_tvd_ft": 11500.0,
        "leg_index": 0, "length_ft": 9800.0, "completed_lateral_ft": 9800.0,
        "drilled_lateral_ft": 9800.0, "lateral_azimuth_deg": 0.0,
        "nearest_neighbor_spacing_ft": 880.0,
    }
    if dsu is not None:
        props["dsu"] = dsu
    return {
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [[-104.1, 32.0], [-104.1, 32.027]]},
        "properties": props,
    }


def _fc(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


_PARCEL = {"type": "Feature",
           "geometry": {"type": "Polygon",
                        "coordinates": [[[-104.11, 31.99], [-104.09, 31.99],
                                         [-104.09, 32.03], [-104.11, 32.03],
                                         [-104.11, 31.99]]]},
           "properties": {"kind": "parcel"}}


def _read_zip(data: bytes) -> tuple[shapefile.Reader, set[str]]:
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    stem = next(n for n in names if n.endswith(".shp"))[:-4]
    r = shapefile.Reader(shp=io.BytesIO(z.read(f"{stem}.shp")),
                         shx=io.BytesIO(z.read(f"{stem}.shx")),
                         dbf=io.BytesIO(z.read(f"{stem}.dbf")))
    return r, names


def test_filters_to_inventory_legs_only():
    data = inventory_shapefile_zip(_fc(
        _PARCEL,
        _leg("pdp_1", "pdp"),                       # existing production: out
        _leg("ctx_1", "pdp", context=True),         # near-parcel background: out
        _leg("gen_1", "generated"),
        _leg("pud_1", "pud"),
    ), "unit_a")
    r, names = _read_zip(data)
    assert names == {"unit_a.shp", "unit_a.shx", "unit_a.dbf", "unit_a.prj", "unit_a.cpg"}
    assert r.shapeType == shapefile.POLYLINE
    recs = r.records()
    assert sorted(rec["WELL_NAME"] for rec in recs) == ["gen_1", "pud_1"]
    assert all(rec["CATEGORY"] != "pdp" for rec in recs)
    assert recs[0]["TVD_FT"] == 11500.0 and recs[0]["SPACING_FT"] == 880.0
    # geometry survives verbatim (WGS84 lon-lat)
    assert r.shape(0).points[0] == (-104.1, 32.0)


def test_prj_is_esri_wgs84():
    data = inventory_shapefile_zip(_fc(_leg("g", "generated")))
    z = zipfile.ZipFile(io.BytesIO(data))
    prj = z.read("narvi_inventory.prj").decode()
    assert prj.startswith('GEOGCS["GCS_WGS_1984"')


def test_bundle_dsu_column_added_when_stamped():
    data = inventory_shapefile_zip(_fc(
        _leg("g1", "generated", dsu="sec_12"),
        _leg("g2", "generated", dsu="sec_13"),
    ), "deal_bundle")
    r, _ = _read_zip(data)
    assert [f[0] for f in r.fields[1:]][0] == "DSU"   # leading column, like the bundle CSV
    assert sorted(rec["DSU"] for rec in r.records()) == ["sec_12", "sec_13"]


def test_pdp_only_fc_raises():
    with pytest.raises(ValueError, match="no inventory sticks"):
        inventory_shapefile_zip(_fc(_PARCEL, _leg("pdp_1", "pdp")))


def test_layer_name_sanitized():
    data = inventory_shapefile_zip(_fc(_leg("g", "generated")), 'bad/name: "x"')
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert all(n.startswith("bad_name___x_") for n in names)
