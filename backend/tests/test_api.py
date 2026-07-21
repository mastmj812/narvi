"""Backend smoke tests via FastAPI TestClient. The /generate path is pure
geometry (no DB); warehouse/scenarios endpoints need the live warehouse and are
covered by the narvi library tests + manual checks."""

from shapely.geometry import mapping

from fastapi.testclient import TestClient
from narvi import synthetic_section
from narvi.viz import _to_wgs_geom

from app.main import app

client = TestClient(app)


def _synthetic_parcel_geojson():
    return mapping(_to_wgs_geom(synthetic_section()))


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_generate_single_returns_geojson_and_gunbarrel():
    body = {
        "parcel": _synthetic_parcel_geojson(),
        # center anchor max-packs the 4,880 ft window at 880 ft -> 6 laterals
        "params": {"spacing_ft": 880, "setback_ft": 200, "formation": "WCA_1",
                   "target_tvd_ft": 11500, "azimuth_deg": 0.0, "anchor": "center"},
        "mode": "single",
    }
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["placed_wells"] == 6 and d["placed_legs"] == 6
    kinds = [f["properties"]["kind"] for f in d["geojson"]["features"]]
    assert kinds.count("leg") == 6 and kinds.count("parcel") == 1
    assert len(d["gunbarrel"]["points"]) == 6


def test_generate_uturn_has_turns():
    body = {
        "parcel": _synthetic_parcel_geojson(),
        "params": {"spacing_ft": 990, "setback_ft": 200, "formation": "WCA_1",
                   "target_tvd_ft": 11500, "azimuth_deg": 0.0, "well_type": "uturn"},
        "mode": "single",
    }
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200
    d = r.json()
    turns = [f for f in d["geojson"]["features"] if f["properties"]["kind"] == "turn"]
    assert len(turns) == 2


def test_export_shapefile_inventory_only():
    # generate a real scenario, then round-trip its FC through the shapefile
    # endpoint with a PDP leg spliced in — the zip must exclude it
    gen = client.post("/api/generate", json={
        "parcel": _synthetic_parcel_geojson(),
        "params": {"spacing_ft": 880, "setback_ft": 200, "formation": "WCA_1",
                   "target_tvd_ft": 11500, "azimuth_deg": 0.0, "anchor": "center"},
        "mode": "single",
    }).json()
    fc = gen["geojson"]
    pdp = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[-104.1, 32.0], [-104.1, 32.03]]},
        "properties": {"kind": "leg", "well_name": "existing_pdp", "category": "pdp"},
    }
    fc["features"].append(pdp)

    r = client.post("/api/export/shapefile", json={"geojson": fc, "layer_name": "unit_a"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="unit_a.zip"' in r.headers["content-disposition"]

    import io
    import zipfile

    import shapefile

    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert {"unit_a.shp", "unit_a.shx", "unit_a.dbf", "unit_a.prj", "unit_a.cpg"} <= set(z.namelist())
    sf = shapefile.Reader(shp=io.BytesIO(z.read("unit_a.shp")),
                          shx=io.BytesIO(z.read("unit_a.shx")),
                          dbf=io.BytesIO(z.read("unit_a.dbf")))
    assert len(sf) == 6  # the 6 generated legs; the spliced PDP leg is excluded
    assert all(rec["CATEGORY"] == "generated" for rec in sf.records())


def test_export_shapefile_pdp_only_is_400():
    fc = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[-104.1, 32.0], [-104.1, 32.03]]},
        "properties": {"kind": "leg", "well_name": "existing_pdp", "category": "pdp"},
    }]}
    r = client.post("/api/export/shapefile", json={"geojson": fc})
    assert r.status_code == 400
    assert "no inventory sticks" in r.json()["detail"]


def test_generate_winerack_requires_zones():
    body = {
        "parcel": _synthetic_parcel_geojson(),
        "params": {"spacing_ft": 880, "setback_ft": 200},
        "mode": "winerack",
    }
    r = client.post("/api/generate", json=body)
    assert r.status_code == 400  # no zones and no source_tvd
