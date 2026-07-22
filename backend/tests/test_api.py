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


def _half_section_geojson():
    from shapely.affinity import scale

    sq = synthetic_section(5280.0)
    return mapping(_to_wgs_geom(scale(sq, xfact=1.0, yfact=0.5, origin=sq.centroid)))


def test_feasibility_with_stipulated_grid_is_db_free():
    r = client.post("/api/parcels/feasibility", json={
        "parcel": _half_section_geojson(),
        "setback_ft": 330, "min_lateral_ft": 4000,
        "grid_azimuth_deg": 0.0,           # stipulated -> no warehouse touch
    })
    assert r.status_code == 200
    dirs = r.json()["directions"]
    assert [d["label"] for d in dirs] == ["grid", "long-axis"]
    grid = dirs[0]
    assert grid["max_lateral_ft"] < 4000 and "min lateral" in grid["note"]
    assert dirs[1]["max_lateral_ft"] > 4000


def test_scan_ranks_configs_and_reproduces():
    parcel = _half_section_geojson()
    feas = client.post("/api/parcels/feasibility", json={
        "parcel": parcel, "setback_ft": 330, "grid_azimuth_deg": 0.0,
    }).json()
    r = client.post("/api/generate/scan", json={
        "parcel": parcel,
        "params": {"spacing_ft": 880, "setback_ft": 330, "formation": "WCA_2",
                   "target_tvd_ft": 11663},
        "azimuths": feas["directions"],
    })
    assert r.status_code == 200
    configs = r.json()["configs"]
    assert configs and configs[0]["azimuth_label"] == "long-axis"
    fts = [c["completed_ft"] for c in configs]
    assert fts == sorted(fts, reverse=True)
    # adopting the winner through /generate reproduces its footage
    w = configs[0]
    g = client.post("/api/generate", json={
        "parcel": parcel,
        "params": {"spacing_ft": w["spacing_ft"], "setback_ft": 330,
                   "formation": "WCA_2", "target_tvd_ft": 11663,
                   "azimuth_deg": w["azimuth_deg"], "well_type": w["well_type"]},
        "mode": "single",
    }).json()
    assert g["placed_wells"] == w["wells"]


def test_sourced_grid_azimuth_zero_wells_falls_back_to_long_axis(monkeypatch):
    # Feasibility-aware auto-azimuth: a sourced grid bearing that places nothing
    # retries the parcel long axis with a loud cross-grid note. Warehouse calls
    # are stubbed so the test stays DB-free.
    from app import engine as eng

    monkeypatch.setattr(eng, "get_connection", lambda: None)
    monkeypatch.setattr(eng, "section_azimuth", lambda conn, parcel, buf: 0.0)
    r = client.post("/api/generate", json={
        "parcel": _half_section_geojson(),
        "params": {"spacing_ft": 880, "setback_ft": 330, "formation": "WCA_2",
                   "target_tvd_ft": 11663},          # N-S grid -> rows < 4,000 ft
        "mode": "single",
        "source_azimuth": True,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["placed_wells"] > 0                     # fallback placed E-W singles
    assert abs(d["azimuth_deg"] - 90.0) < 1.0
    assert any("CROSS-GRID" in n for n in d["warehouse_notes"])

    # a user-STIPULATED azimuth is never second-guessed: explicit 0 deg stays 0
    r2 = client.post("/api/generate", json={
        "parcel": _half_section_geojson(),
        "params": {"spacing_ft": 880, "setback_ft": 330, "formation": "WCA_2",
                   "target_tvd_ft": 11663, "azimuth_deg": 0.0},
        "mode": "single",
    })
    d2 = r2.json()
    assert d2["placed_wells"] == 0
    assert not any("CROSS-GRID" in n for n in d2["warehouse_notes"])
